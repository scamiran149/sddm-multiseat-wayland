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

#ifndef LOGIN1IDLEHINT_H
#define LOGIN1IDLEHINT_H

#include <QObject>
#include <QDBusObjectPath>

class QDBusInterface;

namespace SDDM {

class Login1IdleHint : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(Login1IdleHint)

public:
    explicit Login1IdleHint(QObject *parent = nullptr);
    ~Login1IdleHint();

    bool isAvailable() const;

public Q_SLOTS:
    void setIdle(bool idle);

private:
    bool resolveSessionPath();

    QDBusInterface *m_managerIface = nullptr;
    QDBusInterface *m_sessionIface = nullptr;
    QString m_sessionPath;
    bool m_available = false;
};

}

#endif // LOGIN1IDLEHINT_H