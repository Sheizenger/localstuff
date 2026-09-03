import Foundation

/// Прогноз по одной цели: сколько уже есть, сколько идёт в месяц,
/// когда закроется при текущем темпе и успеваем ли к дедлайну.
struct GoalForecast: Identifiable, Hashable {
    var goal: Goal
    var saved: Double
    var remaining: Double
    var progress: Double
    /// Сколько денег в месяц достаётся этой цели прямо сейчас.
    var monthly: Double
    /// Через сколько месяцев цель начнёт получать деньги (для целей в очереди).
    var startsInMonths: Double
    /// Сколько месяцев до закрытия с сегодняшнего дня. nil — если срок не определён.
    var months: Double?
    var eta: Date?
    /// Сколько нужно откладывать в месяц, чтобы попасть в дедлайн.
    var requiredMonthly: Double?
    /// Запас до дедлайна в месяцах: «+» — успеваем, «−» — опаздываем.
    var deadlineSlack: Double?
    /// Заполняется, когда срок посчитать нельзя: нулевой темп, доля 0% и тому подобное.
    var unfundedReason: String?

    var id: UUID { goal.id }
    var isDone: Bool { remaining <= 0.0001 }
    var funding: GoalFunding { goal.funding }
    /// Цель ждёт своей очереди: деньги пойдут, но позже.
    var isQueued: Bool { !isDone && monthly <= 0.0001 && startsInMonths > 0 }

    var deadlineZone: Zone? {
        guard let slack = deadlineSlack else { return nil }
        if slack >= 1 { return .safe }
        if slack >= -1 { return .warning }
        return .danger
    }

    var horizonText: String {
        if isDone { return "Цель закрыта" }
        if let reason = unfundedReason { return reason }
        guard let months = months else { return "Срок не определён" }
        return Fmt.horizon(months: months)
    }

    var etaText: String {
        if isDone { return "готово" }
        guard let eta = eta else { return "—" }
        return Fmt.monthFull.string(from: eta)
    }
}

enum Forecaster {

    /// Дальше этого горизонта не считаем — 50 лет достаточно, чтобы сказать «слишком долго».
    static let maxMonths = 600

    /// Помесячная симуляция распределения темпа между целями.
    ///
    /// Каждый месяц сначала своё получают параллельные цели (доля темпа; доли нормируются,
    /// если в сумме дают больше 100%), а всё, что осталось — включая долю только что
    /// закрывшейся параллельной цели — переходит очереди, сверху вниз по приоритету.
    static func build(
        goals: [Goal],
        pace: Double,
        savedFor: (Goal) -> Double,
        now: Date = Date()
    ) -> [GoalForecast] {
        let ordered = goals.sorted { lhs, rhs in
            if lhs.priority != rhs.priority { return lhs.priority < rhs.priority }
            return lhs.title.localizedCaseInsensitiveCompare(rhs.title) == .orderedAscending
        }

        let step = max(pace, 0)
        let savedAmounts = ordered.map { savedFor($0) }
        var initialRemaining: [Double] = []
        for (index, goal) in ordered.enumerated() {
            initialRemaining.append(max(goal.targetAmount - savedAmounts[index], 0))
        }

        var remaining = initialRemaining
        var firstMonthGive = [Double](repeating: 0, count: ordered.count)
        var startsIn = [Double?](repeating: nil, count: ordered.count)
        var completion = [Double?](repeating: nil, count: ordered.count)
        var everFunded = [Bool](repeating: false, count: ordered.count)
        var available = 0.0

        // Выдать цели деньги за конкретный месяц и запомнить, когда она закроется.
        func give(_ index: Int, want: Double, month: Int) {
            guard want > 0.0001, remaining[index] > 0.0001 else { return }
            let before = remaining[index]
            let amount = min(min(want, before), available)
            guard amount > 0.0001 else { return }

            remaining[index] = before - amount
            available -= amount
            everFunded[index] = true
            if startsIn[index] == nil { startsIn[index] = Double(month) }
            if month == 0 { firstMonthGive[index] += amount }

            if remaining[index] <= 0.0001 {
                remaining[index] = 0
                // Доля месяца, которая реально понадобилась на закрытие остатка.
                let fraction = min(before / want, 1)
                completion[index] = Double(month) + fraction
            }
        }

        if step > 0 {
            var month = 0
            while month < maxMonths {
                let open = ordered.indices.filter { remaining[$0] > 0.0001 }
                if open.isEmpty { break }

                available = step

                let parallel = open.filter { ordered[$0].funding == .parallel }
                let sumShares = parallel.reduce(0.0) { $0 + max(ordered[$1].share, 0) }
                let factor = sumShares > 1 ? 1 / sumShares : 1
                for index in parallel {
                    give(index, want: step * max(ordered[index].share, 0) * factor, month: month)
                }

                // Остаток темпа уходит в очередь: сначала верхней цели, потом следующей.
                for index in open where ordered[index].funding == .queued {
                    if available <= 0.0001 { break }
                    give(index, want: available, month: month)
                }

                month += 1
            }
        }

        var result: [GoalForecast] = []
        for (index, goal) in ordered.enumerated() {
            let saved = savedAmounts[index]
            let left = initialRemaining[index]
            let months = completion[index]
            let progress = goal.targetAmount > 0
                ? (saved / goal.targetAmount).clamped(0, 1)
                : (left <= 0 ? 1 : 0)

            var eta: Date? = nil
            if left > 0.0001, let value = months, value.isFinite, value >= 0 {
                eta = dateAfter(months: value, from: now)
            }

            var reason: String? = nil
            if left > 0.0001 && months == nil {
                if step <= 0 {
                    reason = "Темп нулевой — срок не определён"
                } else if goal.funding == .parallel && goal.share <= 0 {
                    reason = "Доля 0% — цель не получает денег"
                } else if !everFunded[index] {
                    reason = "Очередь не доходит за 50 лет"
                } else {
                    reason = "Дольше 50 лет при текущем распределении"
                }
            }

            var required: Double? = nil
            var slack: Double? = nil
            if let deadline = goal.deadline, left > 0.0001 {
                let untilDeadline = monthsBetween(now, deadline)
                required = untilDeadline > 0.01 ? left / untilDeadline : left
                if let value = months {
                    slack = untilDeadline - value
                } else {
                    slack = -999
                }
            }

            result.append(
                GoalForecast(
                    goal: goal,
                    saved: saved,
                    remaining: left,
                    progress: progress,
                    monthly: firstMonthGive[index],
                    startsInMonths: startsIn[index] ?? 0,
                    months: months,
                    eta: eta,
                    requiredMonthly: required,
                    deadlineSlack: slack,
                    unfundedReason: reason
                )
            )
        }
        return result
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
