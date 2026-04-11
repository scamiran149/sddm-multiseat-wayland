/***************************************************************************
* Copyright (c) 2025 Samiran Sen <samiran@example.com>
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

#ifndef KWINDPMSBACKEND_H
#define KWINDPMSBACKEND_H

#include <QObject>
#include <QHash>
#include <cstdint>

struct wl_display;
struct wl_output;
struct wl_registry;
struct org_kde_kwin_dpms_manager;
struct org_kde_kwin_dpms;

class QScreen;

namespace SDDM {

class KWinDpmsBackend : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(KWinDpmsBackend)

public:
    explicit KWinDpmsBackend(QObject *parent = nullptr);
    ~KWinDpmsBackend();

    bool initialize();

    bool isAvailable() const;

public Q_SLOTS:
    void screenOff();
    void screenOn();

private Q_SLOTS:
    void onScreenAdded(QScreen *screen);
    void onScreenRemoved(QScreen *screen);

public:
    static void registryGlobal(void *data, struct wl_registry *registry,
                               uint32_t name, const char *interface, uint32_t version);
    static void registryGlobalRemove(void *data, struct wl_registry *registry, uint32_t name);

    static void dpmsSupported(void *data, struct org_kde_kwin_dpms *dpms, uint32_t supported);
    static void dpmsMode(void *data, struct org_kde_kwin_dpms *dpms, uint32_t mode);
    static void dpmsDone(void *data, struct org_kde_kwin_dpms *dpms);

private:
    struct OutputDpms {
        org_kde_kwin_dpms *dpms = nullptr;
        wl_output *output = nullptr;
        bool supported = false;
        uint32_t currentMode = 0;
        bool initialized = false;
    };

    void bindDpmsManager();
    void createDpmsForOutput(wl_output *output);
    void destroyDpmsForOutput(wl_output *output);

    wl_display *m_display = nullptr;
    wl_registry *m_registry = nullptr;
    org_kde_kwin_dpms_manager *m_dpmsManager = nullptr;
    uint32_t m_dpmsManagerName = 0;

    QHash<wl_output *, OutputDpms> m_outputs;
    bool m_available = false;
    bool m_dpmsManagerBound = false;
};

}

#endif // KWINDPMSBACKEND_H