import Foundation

/// Считает, когда срабатывает повторяющееся правило.
///
/// Все даты нормализуются на полдень: так перевод часов и границы суток
/// не сдвигают операцию на соседний день.
enum RecurrenceEngine {

    static let maxSteps = 600

    // MARK: Даты

    static func normalized(_ date: Date) -> Date {
        var parts = Cal.ru.dateComponents([.year, .month, .day], from: date)
        parts.hour = 12
        return Cal.ru.date(from: parts) ?? date
    }

    static func makeDate(year: Int, month: Int, day: Int) -> Date? {
        var normalizedYear = year
        var normalizedMonth = month
        while normalizedMonth > 12 {
            normalizedMonth -= 12
            normalizedYear += 1
        }
        while normalizedMonth < 1 {
            normalizedMonth += 12
            normalizedYear -= 1
        }

        var probe = DateComponents()
        probe.year = normalizedYear
        probe.month = normalizedMonth
        probe.day = 1
        probe.hour = 12
        guard let first = Cal.ru.date(from: probe) else { return nil }

        let length = Cal.ru.range(of: .day, in: .month, for: first)?.count ?? 28
        var parts = DateComponents()
        parts.year = normalizedYear
        parts.month = normalizedMonth
        // День 31 в феврале — это последний день февраля, а не начало марта.
        parts.day = min(max(day, 1), length)
        parts.hour = 12
        return Cal.ru.date(from: parts)
    }

    // MARK: Срабатывания

    /// Первая дата правила — не раньше даты начала.
    static func firstOccurrence(of rule: RecurringRule) -> Date? {
        let start = normalized(rule.startDate)
        let parts = Cal.ru.dateComponents([.year, .month, .day], from: start)
        guard let year = parts.year, let month = parts.month else { return nil }

        switch rule.unit {
        case .month:
            if let candidate = makeDate(year: year, month: month, day: rule.dayOfMonth), candidate >= start {
                return candidate
            }
            return makeDate(year: year, month: month + max(rule.interval, 1), day: rule.dayOfMonth)

        case .year:
            if let candidate = makeDate(year: year, month: rule.monthOfYear, day: rule.dayOfMonth), candidate >= start {
                return candidate
            }
            return makeDate(year: year + max(rule.interval, 1), month: rule.monthOfYear, day: rule.dayOfMonth)

        case .week:
            let target = (rule.weekday >= 1 && rule.weekday <= 7) ? rule.weekday : 2
            var cursor = start
            for _ in 0..<7 {
                if Cal.ru.component(.weekday, from: cursor) == target { return cursor }
                guard let next = Cal.ru.date(byAdding: .day, value: 1, to: cursor) else { return nil }
                cursor = next
            }
            return cursor
        }
    }

    /// Следующее срабатывание после указанной даты.
    static func advance(_ date: Date, rule: RecurringRule) -> Date? {
        let step = max(rule.interval, 1)
        switch rule.unit {
        case .week:
            return Cal.ru.date(byAdding: .day, value: 7 * step, to: date)
        case .month:
            let parts = Cal.ru.dateComponents([.year, .month], from: date)
            guard let year = parts.year, let month = parts.month else { return nil }
            return makeDate(year: year, month: month + step, day: rule.dayOfMonth)
        case .year:
            let parts = Cal.ru.dateComponents([.year], from: date)
            guard let year = parts.year else { return nil }
            return makeDate(year: year + step, month: rule.monthOfYear, day: rule.dayOfMonth)
        }
    }

    /// Все срабатывания в промежутке (after, through].
    static func occurrences(of rule: RecurringRule, after: Date, through: Date) -> [Date] {
        guard rule.isActive, through >= after else { return [] }
        guard var cursor = firstOccurrence(of: rule) else { return [] }

        var result: [Date] = []
        var steps = 0
        let limit = normalized(through)
        let lower = normalized(after)

        while cursor <= limit && steps < maxSteps {
            let withinEnd = rule.endDate.map { cursor <= normalized($0) } ?? true
            if cursor > lower && withinEnd {
                result.append(cursor)
            }
            guard let next = advance(cursor, rule: rule) else { break }
            cursor = next
            steps += 1
        }
        return result
    }

    /// Что пора создать: всё, что наступило до сегодняшнего дня включительно.
    static func pending(for rule: RecurringRule, now: Date = Date()) -> [Date] {
        let from = rule.lastCreatedDate ?? Cal.ru.date(byAdding: .day, value: -1, to: normalized(rule.startDate)) ?? rule.startDate
        return occurrences(of: rule, after: from, through: now)
    }

    /// Ближайшее будущее срабатывание — для строки «ожидается».
    static func next(for rule: RecurringRule, after: Date = Date()) -> Date? {
        let horizon = Cal.ru.date(byAdding: .year, value: 2, to: after) ?? after
        return occurrences(of: rule, after: after, through: horizon).first
    }

    /// Ожидаемые операции до конца месяца — их видно на «Обзоре».
    static func upcoming(rules: [RecurringRule], now: Date = Date(), through: Date) -> [UpcomingEntry] {
        var result: [UpcomingEntry] = []
        for rule in rules where rule.isActive {
            for date in occurrences(of: rule, after: now, through: through) {
                result.append(UpcomingEntry(rule: rule, date: date))
            }
        }
        return result.sorted { $0.date < $1.date }
    }
}
