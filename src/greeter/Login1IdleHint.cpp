#include "Login1IdleHint.h"

#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDebug>

static const QString LOGIN1_SERVICE = QStringLiteral("org.freedesktop.login1");
static const QString LOGIN1_MANAGER_PATH = QStringLiteral("/org/freedesktop/login1");
static const QString LOGIN1_MANAGER_IFACE = QStringLiteral("org.freedesktop.login1.Manager");
static const QString LOGIN1_SESSION_IFACE = QStringLiteral("org.freedesktop.login1.Session");

namespace SDDM {

Login1IdleHint::Login1IdleHint(QObject *parent)
    : QObject(parent)
{
    if (!QDBusConnection::systemBus().interface()->isServiceRegistered(LOGIN1_SERVICE)) {
        qWarning() << "logind is not available on the system bus, IdleHint will not be set";
        return;
    }

    m_managerIface = new QDBusInterface(LOGIN1_SERVICE, LOGIN1_MANAGER_PATH,
                                         LOGIN1_MANAGER_IFACE,
                                         QDBusConnection::systemBus(), this);
    if (!m_managerIface->isValid()) {
        qWarning() << "Failed to create logind manager interface:" << m_managerIface->lastError().message();
        return;
    }

    m_available = resolveSessionPath();
}

Login1IdleHint::~Login1IdleHint()
{
}

bool Login1IdleHint::isAvailable() const
{
    return m_available;
}

bool Login1IdleHint::resolveSessionPath()
{
    pid_t pid = QCoreApplication::applicationPid();

    QDBusReply<QDBusObjectPath> reply = m_managerIface->call(QStringLiteral("GetSessionByPID"), (uint)pid);
    if (!reply.isValid()) {
        qWarning() << "Failed to resolve logind session for PID" << pid << ":" << reply.error().message();
        return false;
    }

    m_sessionPath = reply.value().path();
    qDebug() << "Resolved logind session path:" << m_sessionPath;

    m_sessionIface = new QDBusInterface(LOGIN1_SERVICE, m_sessionPath,
                                          LOGIN1_SESSION_IFACE,
                                          QDBusConnection::systemBus(), this);
    if (!m_sessionIface->isValid()) {
        qWarning() << "Failed to create logind session interface:" << m_sessionIface->lastError().message();
        return false;
    }

    return true;
}

void Login1IdleHint::setIdle(bool idle)
{
    if (!m_available) {
        qDebug() << "IdleHint not available, skipping SetIdleHint(" << idle << ")";
        return;
    }

    QDBusReply<void> reply = m_sessionIface->call(QStringLiteral("SetIdleHint"), idle);
    if (!reply.isValid()) {
        qWarning() << "Failed to call SetIdleHint(" << idle << "):" << reply.error().message();
        return;
    }

    qDebug() << "SetIdleHint(" << idle << ") called successfully on" << m_sessionPath;
}

}
