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

#ifndef IDLECONTROLLER_H
#define IDLECONTROLLER_H

#include <QObject>
#include <QTimer>

namespace SDDM {

class DpmsManager;
class Login1IdleHint;

class IdleController : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(IdleController)

public:
    enum State {
        Active,
        Idle
    };

    explicit IdleController(QObject *parent = nullptr);

    void initialize(int timeoutSeconds);
    State state() const;

public Q_SLOTS:
    void onUserActivity();

Q_SIGNALS:
    void idle();
    void resumed();

private Q_SLOTS:
    void onIdleTimeout();

private:
    State m_state = Active;
    QTimer *m_idleTimer = nullptr;
    int m_timeoutSeconds = 0;
};

}

#endif // IDLECONTROLLER_H