import Foundation

/// Прогноз по одной цели: сколько уже есть, сколько идёт в месяц,
/// когда закроется при текущем темпе и успеваем ли к дедлайну.
struct GoalForecast: Identifiable, Hashable {
    var goal: Goal
    var saved: Double
    var remaining: Double
    var progress: Double
    /// Сколько денег в месяц достаётся этой цели при текущем распределении.
    var monthly: Double
    /// Через сколько месяцев цель начнёт финансироваться (режим «по очереди»).
    var startsInMonths: Double
    /// Сколько месяцев до закрытия с сегодняшнего дня. nil — при нулевом темпе.
    var months: Double?
    var eta: Date?
    /// Сколько нужно откладывать в месяц, чтобы попасть в дедлайн.
    var requiredMonthly: Double?
    /// Запас до дедлайна в месяцах: «+» — успеваем, «−» — опаздываем.
    var deadlineSlack: Double?

    var id: UUID { goal.id }
    var isDone: Bool { remaining <= 0.0001 }
    var isQueued: Bool { !isDone && monthly <= 0 && startsInMonths > 0 }

    var deadlineZone: Zone? {
        guard let slack = deadlineSlack else { return nil }
        if slack >= 1 { return .safe }
        if slack >= -1 { return .warning }
        return .danger
    }

    var horizonText: String {
        if isDone { return "Цель закрыта" }
        guard let months = months else { return "Темп нулевой — срок не определён" }
        return Fmt.horizon(months: months)
    }

    var etaText: String {
        if isDone { return "готово" }
        guard let eta = eta else { return "—" }
        return Fmt.monthFull.string(from: eta)
    }
}

enum Forecaster {

    /// Строит прогноз по всем целям исходя из месячного темпа накоплений.
    ///
    /// - `.priority`: весь темп идёт в первую незакрытую цель, следующая стартует после неё.
    /// - `.shares`: каждая цель получает свою долю темпа (доли нормируются, если сумма > 100%).
    static func build(
        goals: [Goal],
        pace: Double,
        mode: FundingMode,
        savedFor: (Goal) -> Double,
        now: Date = Date()
    ) -> [GoalForecast] {
        let ordered = goals.sorted { lhs, rhs in
            if lhs.priority != rhs.priority { return lhs.priority < rhs.priority }
            return lhs.title.localizedCaseInsensitiveCompare(rhs.title) == .orderedAscending
        }

        let step = max(pace, 0)

        switch mode {
        case .priority:
            return buildSequential(goals: ordered, pace: step, savedFor: savedFor, now: now)
        case .shares:
            return buildParallel(goals: ordered, pace: step, savedFor: savedFor, now: now)
        }
    }

    private static func buildSequential(
        goals: [Goal],
        pace: Double,
        savedFor: (Goal) -> Double,
        now: Date
    ) -> [GoalForecast] {
        var cursor = 0.0
        var isFirstActive = true
        var result: [GoalForecast] = []

        for goal in goals {
            let saved = savedFor(goal)
            let remaining = max(goal.targetAmount - saved, 0)

            if remaining <= 0.0001 {
                result.append(makeForecast(goal: goal, saved: saved, remaining: 0, monthly: 0,
                                           startsIn: 0, months: 0, now: now))
                continue
            }

            let monthly = isFirstActive ? pace : 0
            let startsIn = cursor

            var months: Double? = nil
            if pace > 0 {
                let need = remaining / pace
                months = startsIn + need
                cursor = startsIn + need
            }
            isFirstActive = false

            result.append(makeForecast(goal: goal, saved: saved, remaining: remaining, monthly: monthly,
                                       startsIn: startsIn, months: months, now: now))
        }
        return result
    }

    private static func buildParallel(
        goals: [Goal],
        pace: Double,
        savedFor: (Goal) -> Double,
        now: Date
    ) -> [GoalForecast] {
        let open = goals.filter { max($0.targetAmount - savedFor($0), 0) > 0.0001 }
        let sumShares = open.reduce(0.0) { $0 + max($1.share, 0) }
        let factor = sumShares > 1 ? 1 / sumShares : 1

        var result: [GoalForecast] = []
        for goal in goals {
            let saved = savedFor(goal)
            let remaining = max(goal.targetAmount - saved, 0)

            if remaining <= 0.0001 {
                result.append(makeForecast(goal: goal, saved: saved, remaining: 0, monthly: 0,
                                           startsIn: 0, months: 0, now: now))
                continue
            }

            let monthly = pace * max(goal.share, 0) * factor
            let months: Double? = monthly > 0 ? remaining / monthly : nil
            result.append(makeForecast(goal: goal, saved: saved, remaining: remaining, monthly: monthly,
                                       startsIn: 0, months: months, now: now))
        }
        return result
    }

    private static func makeForecast(
        goal: Goal,
        saved: Double,
        remaining: Double,
        monthly: Double,
        startsIn: Double,
        months: Double?,
        now: Date
    ) -> GoalForecast {
        let progress = goal.targetAmount > 0 ? (saved / goal.targetAmount).clamped(0, 1) : (remaining <= 0 ? 1 : 0)

        var eta: Date? = nil
        if remaining <= 0.0001 {
            eta = nil
        } else if let m = months, m.isFinite, m >= 0, m < 1200 {
            eta = dateAfter(months: m, from: now)
        }

        var required: Double? = nil
        var slack: Double? = nil
        if let deadline = goal.deadline, remaining > 0.0001 {
            let untilDeadline = monthsBetween(now, deadline)
            if untilDeadline > 0.01 {
                required = remaining / untilDeadline
            } else {
                required = remaining
            }
            if let m = months {
                slack = untilDeadline - m
            } else {
                slack = -999
            }
        }

        return GoalForecast(
            goal: goal,
            saved: saved,
            remaining: remaining,
            progress: progress,
            monthly: monthly,
            startsInMonths: startsIn,
            months: months,
            eta: eta,
            requiredMonthly: required,
            deadlineSlack: slack
        )
    }

    /// Дробные месяцы → дата. Считаем через дни, чтобы «2.5 месяца» не округлялось до 3.
    static func dateAfter(months: Double, from: Date) -> Date {
        let days = Int((months * 30.44).rounded())
        return Cal.ru.date(byAdding: .day, value: days, to: from) ?? from
    }

    static func monthsBetween(_ from: Date, _ to: Date) -> Double {
        let seconds = to.timeIntervalSince(from)
        return seconds / (30.44 * 24 * 3600)
    }
}
