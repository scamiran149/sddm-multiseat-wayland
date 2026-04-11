#include "KWinDpmsBackend.h"

#include <QGuiApplication>
#include <QScreen>
#include <QDebug>

#include <QtGui/qguiapplication_platform.h>
#include <QtCore/qnativeinterface.h>

#include <wayland-client-protocol.h>
#include <wayland-client.h>

#include "wayland-dpms-client-protocol.h"

namespace SDDM {

static const struct org_kde_kwin_dpms_listener dpmsListener = {
    .supported = KWinDpmsBackend::dpmsSupported,
    .mode = KWinDpmsBackend::dpmsMode,
    .done = KWinDpmsBackend::dpmsDone,
};

KWinDpmsBackend::KWinDpmsBackend(QObject *parent)
    : QObject(parent)
{
}

KWinDpmsBackend::~KWinDpmsBackend()
{
    for (auto it = m_outputs.begin(); it != m_outputs.end(); ++it) {
        if (it->dpms)
            org_kde_kwin_dpms_release(it->dpms);
    }
    if (m_dpmsManager)
        org_kde_kwin_dpms_manager_destroy(m_dpmsManager);
    if (m_registry)
        wl_registry_destroy(m_registry);
}

bool KWinDpmsBackend::initialize()
{
    auto *waylandApp = qGuiApp->nativeInterface<QNativeInterface::QWaylandApplication>();
    if (!waylandApp) {
        qWarning() << "KWinDpmsBackend: Not running on a Wayland platform";
        return false;
    }

    m_display = waylandApp->display();
    if (!m_display) {
        qWarning() << "KWinDpmsBackend: Failed to get wl_display";
        return false;
    }

    m_registry = wl_display_get_registry(m_display);
    if (!m_registry) {
        qWarning() << "KWinDpmsBackend: Failed to get wl_registry";
        return false;
    }

    static const struct wl_registry_listener registryListener = {
        .global = registryGlobal,
        .global_remove = registryGlobalRemove,
    };
    wl_registry_add_listener(m_registry, &registryListener, this);

    wl_display_roundtrip(m_display);

    if (!m_dpmsManagerBound) {
        qWarning() << "KWinDpmsBackend: org_kde_kwin_dpms_manager not available";
        return false;
    }

    const QList<QScreen *> screens = qGuiApp->screens();
    for (QScreen *screen : screens) {
        auto *waylandScreen = screen->nativeInterface<QNativeInterface::QWaylandScreen>();
        if (!waylandScreen) {
            qWarning() << "KWinDpmsBackend: Could not get QWaylandScreen for" << screen->name();
            continue;
        }
        wl_output *output = waylandScreen->output();
        if (!output) {
            qWarning() << "KWinDpmsBackend: Could not get wl_output for" << screen->name();
            continue;
        }
        createDpmsForOutput(output);
    }

    wl_display_roundtrip(m_display);

    connect(qGuiApp, &QGuiApplication::screenAdded, this, &KWinDpmsBackend::onScreenAdded);
    connect(qGuiApp, &QGuiApplication::screenRemoved, this, &KWinDpmsBackend::onScreenRemoved);

    m_available = true;
    qDebug() << "KWinDpmsBackend: initialized successfully with" << m_outputs.size() << "output(s)";
    return true;
}

bool KWinDpmsBackend::isAvailable() const
{
    return m_available;
}

void KWinDpmsBackend::screenOff()
{
    if (!m_available)
        return;

    for (auto it = m_outputs.begin(); it != m_outputs.end(); ++it) {
        if (it->dpms && it->supported) {
            qDebug() << "KWinDpmsBackend: requesting DPMS Off for output";
            org_kde_kwin_dpms_set(it->dpms, ORG_KDE_KWIN_DPMS_MODE_OFF);
        }
    }
    wl_display_flush(m_display);
}

void KWinDpmsBackend::screenOn()
{
    if (!m_available)
        return;

    for (auto it = m_outputs.begin(); it != m_outputs.end(); ++it) {
        if (it->dpms && it->supported) {
            qDebug() << "KWinDpmsBackend: requesting DPMS On for output";
            org_kde_kwin_dpms_set(it->dpms, ORG_KDE_KWIN_DPMS_MODE_ON);
        }
    }
    wl_display_flush(m_display);
}

void KWinDpmsBackend::onScreenAdded(QScreen *screen)
{
    auto *waylandScreen = screen->nativeInterface<QNativeInterface::QWaylandScreen>();
    if (!waylandScreen)
        return;
    wl_output *output = waylandScreen->output();
    if (!output)
        return;
    createDpmsForOutput(output);
    wl_display_roundtrip(m_display);
}

void KWinDpmsBackend::onScreenRemoved(QScreen *screen)
{
    auto *waylandScreen = screen->nativeInterface<QNativeInterface::QWaylandScreen>();
    if (!waylandScreen)
        return;
    wl_output *output = waylandScreen->output();
    if (!output)
        return;
    destroyDpmsForOutput(output);
}

void KWinDpmsBackend::bindDpmsManager()
{
    if (!m_dpmsManagerName)
        return;
    m_dpmsManager = static_cast<org_kde_kwin_dpms_manager *>(
        wl_registry_bind(m_registry, m_dpmsManagerName, &org_kde_kwin_dpms_manager_interface, 1));
    if (!m_dpmsManager) {
        qWarning() << "KWinDpmsBackend: Failed to bind org_kde_kwin_dpms_manager";
        return;
    }
    m_dpmsManagerBound = true;
    qDebug() << "KWinDpmsBackend: bound org_kde_kwin_dpms_manager";
}

void KWinDpmsBackend::createDpmsForOutput(wl_output *output)
{
    if (!m_dpmsManager || !output)
        return;

    if (m_outputs.contains(output))
        return;

    org_kde_kwin_dpms *dpms = org_kde_kwin_dpms_manager_get(m_dpmsManager, output);
    if (!dpms) {
        qWarning() << "KWinDpmsBackend: Failed to create org_kde_kwin_dpms for output";
        return;
    }

    OutputDpms od;
    od.dpms = dpms;
    od.output = output;
    org_kde_kwin_dpms_add_listener(dpms, &dpmsListener, this);
    m_outputs.insert(output, od);
}

void KWinDpmsBackend::destroyDpmsForOutput(wl_output *output)
{
    auto it = m_outputs.find(output);
    if (it == m_outputs.end())
        return;

    if (it->dpms)
        org_kde_kwin_dpms_release(it->dpms);
    m_outputs.erase(it);
}

void KWinDpmsBackend::registryGlobal(void *data, struct wl_registry *registry,
                                      uint32_t name, const char *interface, uint32_t version)
{
    Q_UNUSED(registry);
    Q_UNUSED(version);

    auto *self = static_cast<KWinDpmsBackend *>(data);
    if (strcmp(interface, org_kde_kwin_dpms_manager_interface.name) == 0) {
        self->m_dpmsManagerName = name;
        self->bindDpmsManager();
    }
}

void KWinDpmsBackend::registryGlobalRemove(void *data, struct wl_registry *registry, uint32_t name)
{
    Q_UNUSED(registry);
    auto *self = static_cast<KWinDpmsBackend *>(data);
    if (name == self->m_dpmsManagerName) {
        qWarning() << "KWinDpmsBackend: org_kde_kwin_dpms_manager removed";
        self->m_dpmsManager = nullptr;
        self->m_dpmsManagerBound = false;
        self->m_available = false;
    }
}

void KWinDpmsBackend::dpmsSupported(void *data, struct org_kde_kwin_dpms *dpms, uint32_t supported)
{
    auto *self = static_cast<KWinDpmsBackend *>(data);
    for (auto it = self->m_outputs.begin(); it != self->m_outputs.end(); ++it) {
        if (it->dpms == dpms) {
            it->supported = (supported != 0);
            qDebug() << "KWinDpmsBackend: output DPMS supported:" << it->supported;
            break;
        }
    }
}

void KWinDpmsBackend::dpmsMode(void *data, struct org_kde_kwin_dpms *dpms, uint32_t mode)
{
    auto *self = static_cast<KWinDpmsBackend *>(data);
    for (auto it = self->m_outputs.begin(); it != self->m_outputs.end(); ++it) {
        if (it->dpms == dpms) {
            it->currentMode = mode;
            qDebug() << "KWinDpmsBackend: output DPMS mode:" << mode;
            break;
        }
    }
}

void KWinDpmsBackend::dpmsDone(void *data, struct org_kde_kwin_dpms *dpms)
{
    auto *self = static_cast<KWinDpmsBackend *>(data);
    for (auto it = self->m_outputs.begin(); it != self->m_outputs.end(); ++it) {
        if (it->dpms == dpms) {
            it->initialized = true;
            qDebug() << "KWinDpmsBackend: output DPMS initialization done, supported:" << it->supported << "mode:" << it->currentMode;
            break;
        }
    }
}

}