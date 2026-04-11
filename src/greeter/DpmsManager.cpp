#include "DpmsManager.h"
#include "KWinDpmsBackend.h"

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

    DpmsCallParams configOn;
    configOn.service = mainConfig.GreeterIdle.DpmsOnService.get();
    configOn.path = mainConfig.GreeterIdle.DpmsOnPath.get();
    configOn.interface = mainConfig.GreeterIdle.DpmsOnInterface.get();
    configOn.method = mainConfig.GreeterIdle.DpmsOnMethod.get();

    bool hasFullOffOverride = configOff.isValid();
    bool hasFullOnOverride = configOn.isValid();
    bool hasPartialOffOverride = !configOff.service.isEmpty() || !configOff.path.isEmpty() || !configOff.interface.isEmpty() || !configOff.method.isEmpty();
    bool hasPartialOnOverride = !configOn.service.isEmpty() || !configOn.path.isEmpty() || !configOn.interface.isEmpty() || !configOn.method.isEmpty();

    if (hasFullOffOverride && hasFullOnOverride) {
        m_offParams = configOff;
        m_onParams = configOn;
        m_useDbusOverride = true;
        m_available = true;
        qDebug() << "DPMS: using configured DBus override for off:" << m_offParams.service << m_offParams.path << m_offParams.interface << m_offParams.method;
        qDebug() << "DPMS: using configured DBus override for on:" << m_onParams.service << m_onParams.path << m_onParams.interface << m_onParams.method;
        return;
    }

    if (hasPartialOffOverride) {
        qWarning() << "DPMS: partial off override detected (requires all of service/path/interface/method). Falling back to native backend.";
    }
    if (hasPartialOnOverride) {
        qWarning() << "DPMS: partial on override detected (requires all of service/path/interface/method). Falling back to native backend.";
    }

    m_nativeBackend = new KWinDpmsBackend(this);
    if (m_nativeBackend->initialize()) {
        m_available = true;
        qDebug() << "DPMS: using native KWin kde-dpms backend";
        return;
    }

    qWarning() << "DPMS: native KWin backend not available, DPMS will not function";
    m_available = false;
}

bool DpmsManager::isAvailable() const
{
    return m_available;
}

void DpmsManager::screenOff()
{
    if (!m_available)
        return;

    if (m_useDbusOverride) {
        callDpms(m_offParams, false);
    } else if (m_nativeBackend) {
        m_nativeBackend->screenOff();
    }
}

void DpmsManager::screenOn()
{
    if (!m_available)
        return;

    if (m_useDbusOverride) {
        callDpms(m_onParams, true);
    } else if (m_nativeBackend) {
        m_nativeBackend->screenOn();
    }
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