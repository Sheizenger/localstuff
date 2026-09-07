import Foundation

/// Решает, о чём стоит сообщить. Чистая логика без системных вызовов —
/// её можно прогнать в самопроверке и не гадать, что именно увидит человек.
enum NotificationPlanner {

    /// Пороги лимита свободных трат, о которых имеет смысл предупредить.
    static let thresholds: [Double] = [0.6, 0.85, 1.0]

    static func plan(data: AppData, analytics: Analytics, now: Date) -> [PlannedNotification] {
        let settings = data.notifications
        guard settings.enabled else { return [] }

        var result: [PlannedNotification] = []
        let currency = data.profile.currencyCode
        let month = MonthKey(date: now)

        if settings.limitThresholds {
            result.append(contentsOf: limitNotifications(analytics: analytics, month: month, currency: currency))
        }
        if settings.upcomingPayments {
            result.append(contentsOf: upcomingNotifications(data: data, now: now, leadDays: settings.leadDays, currency: currency))
        }
        if settings.monthSummary {
            result.append(contentsOf: summaryNotifications(data: data, analytics: analytics, now: now, currency: currency))
        }
        if settings.payday {
            result.append(contentsOf: paydayNotifications(data: data, analytics: analytics, now: now, currency: currency))
        }
        return result
    }

    // MARK: Пороги лимита

    static func limitNotifications(analytics: Analytics, month: MonthKey, currency: String) -> [PlannedNotification] {
        let status = analytics.budgetStatus
        guard status.limit > 0, status.spent > 0 else { return [] }

        let share = status.spent / status.limit
        var result: [PlannedNotification] = []

        for threshold in thresholds where share >= threshold {
            let percent = Int(threshold * 100)
            let title: String
            let body: String

            if threshold >= 1.0 {
                title = "Лимит свободных трат исчерпан"
                body = "Потрачено \(Fmt.money(status.spent, code: currency)) при лимите \(Fmt.money(status.limit, code: currency)). Перерасход \(Fmt.money(status.spent - status.limit, code: currency)) — это не повод лезть в накопления, покупка переносится на следующий месяц."
            } else {
                title = "Свободных трат: \(percent)% лимита"
                body = "Потрачено \(Fmt.money(status.spent, code: currency)) из \(Fmt.money(status.limit, code: currency)). Осталось \(Fmt.daysWord(status.daysLeft)) и \(Fmt.money(status.dailyAllowance, code: currency)) в день."
            }

            result.append(
                PlannedNotification(id: "limit-\(percent)-\(month.id)", title: title, body: body)
            )
        }
        return result
    }

    // MARK: Предстоящие платежи

    static func upcomingNotifications(data: AppData, now: Date, leadDays: Int, currency: String) -> [PlannedNotification] {
        let horizon = Cal.ru.date(byAdding: .day, value: max(leadDays, 0) + 30, to: now) ?? now
        let entries = RecurrenceEngine.upcoming(rules: data.recurring, now: now, through: horizon)

        var result: [PlannedNotification] = []
        for entry in entries {
            guard let fireDate = Cal.ru.date(byAdding: .day, value: -max(leadDays, 0), to: entry.date) else { continue }
            let stamp = Fmt.stampKey.string(from: entry.date)
            let money = Fmt.money(entry.rule.amount, code: currency)

            let title = entry.rule.flow == .income
                ? "Скоро поступление: \(entry.rule.title)"
                : "Скоро списание: \(entry.rule.title)"
            let body = entry.rule.autoCreate
                ? "\(Fmt.daySimple.string(from: entry.date)) — \(money). Приложение запишет это само."
                : "\(Fmt.daySimple.string(from: entry.date)) — \(money). Автозапись выключена, внесите операцию сами."

            result.append(
                PlannedNotification(
                    id: "due-\(entry.rule.id.uuidString)-\(stamp)",
                    title: title,
                    body: body,
                    // Если предупреждать уже поздно, показываем сразу.
                    date: fireDate > now ? at9(fireDate) : nil
                )
            )
        }
        return result
    }

    // MARK: Итог месяца

    static func summaryNotifications(data: AppData, analytics: Analytics, now: Date, currency: String) -> [PlannedNotification] {
        let day = Cal.ru.component(.day, from: now)
        guard day <= 3 else { return [] }

        let previous = MonthKey(date: now).adding(-1)
        let stats = analytics.stats(for: previous)
        guard stats.hasData else { return [] }

        let plan = data.profile.savingsPlan
        var body = "Доход \(Fmt.money(stats.income, code: currency)), расходы \(Fmt.money(stats.expense, code: currency)). Осталось \(Fmt.signedMoney(stats.net, code: currency))."
        if plan > 0 {
            let delta = stats.net - plan
            body += delta >= 0
                ? " Это на \(Fmt.money(delta, code: currency)) больше плана."
                : " Это на \(Fmt.money(-delta, code: currency)) меньше плана."
        }

        return [
            PlannedNotification(
                id: "summary-\(previous.id)",
                title: "\(previous.fullTitle) закрыт",
                body: body
            )
        ]
    }

    // MARK: День зарплаты

    static func paydayNotifications(data: AppData, analytics: Analytics, now: Date, currency: String) -> [PlannedNotification] {
        let todayIncome = data.transactions
            .filter { $0.flow == .income && Cal.ru.isDate($0.date, inSameDayAs: now) }
            .reduce(0.0) { $0 + $1.amount }
        guard todayIncome > 0 else { return [] }

        let openGoals = analytics.activeGoals.filter { analytics.saved(for: $0) < $0.targetAmount - 0.01 }
        guard !openGoals.isEmpty else { return [] }

        let plan = data.profile.savingsPlan
        let target = openGoals.first
        let stamp = Fmt.stampKey.string(from: now)

        var body = "Пришло \(Fmt.money(todayIncome, code: currency))."
        if plan > 0, let target = target {
            body += " Решение принимается до трат: перевести \(Fmt.money(plan, code: currency)) в «\(target.title)»?"
        } else if let target = target {
            body += " Самое время отложить в «\(target.title)» — до того, как деньги разойдутся."
        }

        return [
            PlannedNotification(id: "payday-\(stamp)", title: "Доход пришёл", body: body)
        ]
    }

    // MARK: Мелочи

    /// Уведомления о будущем приходят утром, а не среди ночи.
    static func at9(_ date: Date) -> Date {
        var parts = Cal.ru.dateComponents([.year, .month, .day], from: date)
        parts.hour = 9
        parts.minute = 0
        return Cal.ru.date(from: parts) ?? date
    }
}
