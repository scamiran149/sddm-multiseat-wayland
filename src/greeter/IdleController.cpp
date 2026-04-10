#include "IdleController.h"

#include "Configuration.h"

#include <QDebug>

namespace SDDM {

IdleController::IdleController(QObject *parent)
    : QObject(parent)
    , m_idleTimer(new QTimer(this))
{
    m_idleTimer->setSingleShot(true);
    connect(m_idleTimer, &QTimer::timeout, this, &IdleController::onIdleTimeout);
}

void IdleController::initialize(int timeoutSeconds)
{
    m_timeoutSeconds = timeoutSeconds;
    if (m_timeoutSeconds <= 0) {
        qDebug() << "Idle handling disabled (timeout <= 0)";
        return;
    }
    qDebug() << "Idle controller initialized with timeout" << m_timeoutSeconds << "seconds";
    m_idleTimer->start(m_timeoutSeconds * 1000);
}

IdleController::State IdleController::state() const
{
    return m_state;
}

void IdleController::onUserActivity()
{
    if (m_timeoutSeconds <= 0)
        return;

    if (m_state == Idle) {
        m_state = Active;
        qDebug() << "Greeter resumed from idle";
        Q_EMIT resumed();
    }

    m_idleTimer->start(m_timeoutSeconds * 1000);
}

void IdleController::onIdleTimeout()
{
    if (m_state == Active) {
        m_state = Idle;
        qDebug() << "Greeter idle timeout reached";
        Q_EMIT idle();
    }
}

}