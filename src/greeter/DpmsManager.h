/***************************************************************************
* Copyright (c) 2025 Samiran Sen <samiran@example.com>
*
* This program is free software; you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation; either version 2 of the License. or
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

#ifndef DPMSMANAGER_H
#define DPMSMANAGER_H

#include <QObject>

class QDBusInterface;

namespace SDDM {

struct DpmsCallParams {
    QString service;
    QString path;
    QString interface;
    QString method;
    bool isValid() const;
};

class DpmsManager : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(DpmsManager)

public:
    explicit DpmsManager(QObject *parent = nullptr);
    ~DpmsManager();

    void initialize();

    bool isAvailable() const;

public Q_SLOTS:
    void screenOff();
    void screenOn();

private:
    DpmsCallParams m_offParams;
    DpmsCallParams m_onParams;
    bool m_available = false;

    void callDpms(const DpmsCallParams &params, bool on);

    static DpmsCallParams kwinDefaultOff();
    static DpmsCallParams kwinDefaultOn();
};

}

#endif // DPMSMANAGER_H