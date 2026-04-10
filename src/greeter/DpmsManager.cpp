#include "DpmsManager.h"

#include "Configuration.h"

#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDebug>

namespace SDDM {

bool DpmsCallParams::isValid() const
{
    return !service.isEmpty() && !path.isEmpty() && !interface.isEmpty() && !method.isEmpty();
}

DpmsCallParams DpmsManager::kwinDefaultOff()
{
    return {
        QStringLiteral("org.kde.KWin"),
        QStringLiteral("/ScreenSaver"),
        QStringLiteral("org.freedesktop.ScreenSaver"),
        QStringLiteral("SetActive")
    };
}

DpmsCallParams DpmsManager::kwinDefaultOn()
{
    return {
        QStringLiteral("org.kde.KWin"),
        QStringLiteral("/ScreenSaver"),
        QStringLiteral("org.freedesktop.ScreenSaver"),
        QStringLiteral("SetActive")
    };
}

DpmsManager::DpmsManager(QObject *parent)
    : QObject(parent)
{
}

DpmsManager::~DpmsManager()
{
}

void DpmsManager::initialize()
{
    DpmsCallParams configOff;
    configOff.service = mainConfig.GreeterIdle.DpmsOffService.get();
    configOff.path = mainConfig.GreeterIdle.DpmsOffPath.get();
    configOff.interface = mainConfig.GreeterIdle.DpmsOffInterface.get();
    configOff.method = mainConfig.GreeterIdle.DpmsOffMethod.get();

    if (configOff.isValid()) {
        m_offParams = configOff;
        qDebug() << "Using configured DPMS off call:" << m_offParams.service << m_offParams.path << m_offParams.interface << m_offParams.method;
    } else if (!configOff.service.isEmpty() || !configOff.path.isEmpty() || !configOff.interface.isEmpty() || !configOff.method.isEmpty()) {
        qWarning() << "Partial DPMS off override detected (requires all of service/path/interface/method). Falling back to built-in default.";
        m_offParams = kwinDefaultOff();
    } else {
        m_offParams = kwinDefaultOff();
        qDebug() << "Using built-in KWin DPMS off default";
    }

    DpmsCallParams configOn;
    configOn.service = mainConfig.GreeterIdle.DpmsOnService.get();
    configOn.path = mainConfig.GreeterIdle.DpmsOnPath.get();
    configOn.interface = mainConfig.GreeterIdle.DpmsOnInterface.get();
    configOn.method = mainConfig.GreeterIdle.DpmsOnMethod.get();

    if (configOn.isValid()) {
        m_onParams = configOn;
        qDebug() << "Using configured DPMS on call:" << m_onParams.service << m_onParams.path << m_onParams.interface << m_onParams.method;
    } else if (!configOn.service.isEmpty() || !configOn.path.isEmpty() || !configOn.interface.isEmpty() || !configOn.method.isEmpty()) {
        qWarning() << "Partial DPMS on override detected (requires all of service/path/interface/method). Falling back to built-in default.";
        m_onParams = kwinDefaultOn();
    } else {
        m_onParams = kwinDefaultOn();
        qDebug() << "Using built-in KWin DPMS on default";
    }

    m_available = true;
}

bool DpmsManager::isAvailable() const
{
    return m_available;
}

void DpmsManager::screenOff()
{
    callDpms(m_offParams, false);
}

void DpmsManager::screenOn()
{
    callDpms(m_onParams, true);
}

void DpmsManager::callDpms(const DpmsCallParams &params, bool on)
{
    QDBusInterface iface(params.service, params.path, params.interface,
                          QDBusConnection::sessionBus(), this);

    if (!iface.isValid()) {
        qWarning() << "DPMS: failed to create D-Bus interface for" << params.service << params.path << params.interface
                   << ":" << iface.lastError().message();
        qWarning() << "DPMS: trying system bus as fallback";
        QDBusInterface sysIface(params.service, params.path, params.interface,
                                 QDBusConnection::systemBus(), this);
        if (!sysIface.isValid()) {
            qWarning() << "DPMS: system bus fallback also failed:" << sysIface.lastError().message();
            return;
        }
        QDBusReply<void> reply = sysIface.call(params.method, !on);
        if (!reply.isValid()) {
            qWarning() << "DPMS: D-Bus call failed:" << reply.error().message();
        } else {
            qDebug() << "DPMS: screen" << (on ? "on" : "off") << "via system bus";
        }
        return;
    }

    QDBusReply<void> reply = iface.call(params.method, !on);
    if (!reply.isValid()) {
        qWarning() << "DPMS: D-Bus call failed:" << reply.error().message();
        return;
    }

    qDebug() << "DPMS: screen" << (on ? "on" : "off") << "via session bus";
}

}