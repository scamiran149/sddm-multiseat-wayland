/***************************************************************************
 * Copyright (c) 2021 Aleix Pol Gonzalez <aleixpol@kde.org>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the
 * Free Software Foundation, Inc.,
 * 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 ***************************************************************************/

#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QStandardPaths>
#include <QThread>

#include "Configuration.h"

#include "VirtualTerminal.h"
#include "waylandhelper.h"
#include "waylandsocketwatcher.h"

#include <fcntl.h>
#include <unistd.h>

namespace SDDM {

WaylandHelper::WaylandHelper(QObject *parent)
    : QObject(parent), m_environment(QProcessEnvironment::systemEnvironment()),
      m_watcher(new WaylandSocketWatcher(
          m_environment.value(QStringLiteral("WAYLAND_DISPLAY")), this)) {
  // Ensure XDG_RUNTIME_DIR is set so KWin can start even if
  // pam_systemd failed to create one.
  QString runtimeDir = m_environment.value(QStringLiteral("XDG_RUNTIME_DIR"));
  if (runtimeDir.isEmpty()) {
    const QString seatName = m_environment.value(QStringLiteral("XDG_SEAT"));
    runtimeDir = QStringLiteral("/tmp/runtime-sddm/%1").arg(
        seatName.isEmpty() ? QStringLiteral("seat0") : seatName);
  }

  QDir dir;
  dir.mkpath(runtimeDir);
  // 0700 permissions are required by Wayland
  QFile::setPermissions(runtimeDir,
                        QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);

  m_environment.insert(QStringLiteral("XDG_RUNTIME_DIR"), runtimeDir);
  qputenv("XDG_RUNTIME_DIR", runtimeDir.toLocal8Bit());
}

bool WaylandHelper::startCompositor(const QString &cmd) {
  if (!startDbus())
    return false;

  m_watcher->start();
  return startProcess(cmd, &m_serverProcess);
}

void stopProcess(QProcess *process) {
  if (process && process->state() != QProcess::NotRunning) {
    qInfo() << "Stopping..." << process->program();
    process->terminate();
    if (!process->waitForFinished(5000)) {
      process->kill();
      process->waitForFinished(25000);
    }
    process->deleteLater();
    process = nullptr;
  }
}

void WaylandHelper::stop() {
  m_watcher->stop();
  stopProcess(m_greeterProcess);
  stopProcess(m_serverProcess);
  stopProcess(m_dbusProcess);
}

QString WaylandHelper::sessionBusAddress() const {
  const QString runtimeDir =
      m_environment.value(QStringLiteral("XDG_RUNTIME_DIR"));
  const QString seatName = m_environment.value(QStringLiteral("XDG_SEAT"));
  const QString socketName = seatName.isEmpty()
                                 ? QStringLiteral("wayland-dbus")
                                 : QStringLiteral("wayland-dbus-%1").arg(seatName);

  return QStringLiteral("unix:path=%1/%2").arg(runtimeDir, socketName);
}

bool WaylandHelper::startDbus() {
  if (m_dbusProcess)
    return true;

  const QString runtimeDir =
      m_environment.value(QStringLiteral("XDG_RUNTIME_DIR"));
  if (runtimeDir.isEmpty()) {
    qWarning() << "Cannot start D-Bus without XDG_RUNTIME_DIR";
    return false;
  }

  const QString busAddress = sessionBusAddress();
  const QString socketPath = busAddress.section(QLatin1Char('='), 1);
  if (QFileInfo::exists(socketPath)) {
    if (!QFile::remove(socketPath)) {
      qWarning() << "Failed to remove stale D-Bus socket" << socketPath;
      return false;
    }
  }

  m_environment.insert(QStringLiteral("DBUS_SESSION_BUS_ADDRESS"), busAddress);

  m_dbusProcess = new QProcess(this);
  m_dbusProcess->setProcessEnvironment(m_environment);
  m_dbusProcess->start(QStringLiteral("dbus-daemon"),
                       {QStringLiteral("--session"),
                        QStringLiteral("--address=%1").arg(busAddress),
                        QStringLiteral("--nofork")});
  if (!m_dbusProcess->waitForStarted()) {
    qWarning() << "Failed to start D-Bus session bus"
               << m_dbusProcess->errorString();
    m_dbusProcess->deleteLater();
    m_dbusProcess = nullptr;
    return false;
  }

  int retries = 50;
  while (retries-- > 0 && !QFileInfo::exists(socketPath) &&
         m_dbusProcess->state() != QProcess::NotRunning) {
    QThread::msleep(20);
  }

  if (!QFileInfo::exists(socketPath)) {
    qWarning() << "D-Bus socket was not created at" << socketPath;
    stopProcess(m_dbusProcess);
    m_dbusProcess = nullptr;
    return false;
  }

  return true;
}

bool WaylandHelper::startProcess(const QString &cmd, QProcess **p) {
  auto *process = new QProcess(this);
  process->setProcessEnvironment(m_environment);
  process->setInputChannelMode(QProcess::ForwardedInputChannel);
  connect(process, &QProcess::readyReadStandardError, this,
          [process] { qWarning() << process->readAllStandardError(); });
  connect(process, &QProcess::readyReadStandardOutput, this,
          [process] { qInfo() << process->readAllStandardOutput(); });
  qDebug() << "Starting Wayland process" << cmd
           << m_environment.value(QStringLiteral("USER"));
  connect(process,
          QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
          process, [](int exitCode, QProcess::ExitStatus exitStatus) {
            qDebug() << "wayland compositor finished" << exitCode << exitStatus;
            if (exitCode != 0 || exitStatus != QProcess::NormalExit)
              QCoreApplication::instance()->quit();
          });

  auto args = QProcess::splitCommand(cmd);
  const auto program = args.takeFirst();

  QString waylandDisplay = m_environment.value(QStringLiteral("WAYLAND_DISPLAY"));
  if (!waylandDisplay.isEmpty()) {
    args << QStringLiteral("--socket") << waylandDisplay;
  }

  process->start(program, args);
  if (!process->waitForStarted(10000)) {
    qWarning("Failed to start \"%s\": %s", qPrintable(cmd),
             qPrintable(process->errorString()));
    return false;
  }

  if (p)
    *p = process;

  qDebug() << "started succesfully" << cmd;
  return true;
}

void WaylandHelper::startGreeter(const QString &cmd) {
  auto args = QProcess::splitCommand(cmd);

  m_greeterProcess = new QProcess(this);
  m_greeterProcess->setProgram(args.takeFirst());
  m_greeterProcess->setArguments(args);
  connect(m_greeterProcess, &QProcess::readyReadStandardError, this,
          [this] { qWarning() << m_greeterProcess->readAllStandardError(); });
  connect(m_greeterProcess, &QProcess::readyReadStandardOutput, this,
          [this] { qInfo() << m_greeterProcess->readAllStandardOutput(); });
  connect(m_greeterProcess,
          QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
          m_greeterProcess, [](int exitCode, QProcess::ExitStatus exitStatus) {
            qDebug() << "wayland greeter finished" << exitCode << exitStatus;
            QCoreApplication::instance()->quit();
          });
  if (m_watcher->status() == WaylandSocketWatcher::Started) {
    m_environment.insert(QStringLiteral("WAYLAND_DISPLAY"),
                         m_watcher->socketName());
    m_greeterProcess->setProcessEnvironment(m_environment);
    m_greeterProcess->start();
  } else if (m_watcher->status() == WaylandSocketWatcher::Failed) {
    Q_EMIT failed();
  } else {
    connect(m_watcher, &WaylandSocketWatcher::failed, this,
            &WaylandHelper::failed);
    connect(m_watcher, &WaylandSocketWatcher::started, this, [this] {
      m_watcher->stop();
      m_environment.insert(QStringLiteral("WAYLAND_DISPLAY"),
                           m_watcher->socketName());
      m_greeterProcess->setProcessEnvironment(m_environment);
      m_greeterProcess->start();
    });
  }
}

} // namespace SDDM
