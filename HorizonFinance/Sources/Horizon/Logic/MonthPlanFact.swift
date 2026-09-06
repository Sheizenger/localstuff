import Foundation

/// Свод месяца: план против того, чем месяц закончится.
///
/// Смысл в том, чтобы видеть взаимозачёт. Лимит свободных трат намеренно жёсткий и
/// не смягчается экономией на аренде, но человек должен понимать: перерасход в кафе
/// может быть перекрыт тем, что обязательные вышли дешевле — или не перекрыт.
struct MonthPlanFact {
    var month: MonthKey
    /// Какая часть месяца прошла, 0…1.
    var dayProgress: Double
    var isComplete: Bool

    var incomePlan: Double
    var incomeFact: Double
    /// Ещё придёт по регулярным шаблонам до конца месяца.
    var incomeExpected: Double

    var essentialsPlan: Double
    var essentialsFact: Double
    var essentialsExpected: Double

    var flexibleLimit: Double
    var flexibleFact: Double
    var flexibleExpected: Double
    /// Экстраполяция свободных трат на конец месяца по текущему темпу.
    var flexibleProjected: Double

    var savingsPlan: Double

    // MARK: Прогнозы

    /// Доход: факт плюс ожидаемое; пока месяц идёт, план не может быть ниже известного.
    var incomeForecast: Double {
        let known = incomeFact + incomeExpected
        return isComplete ? incomeFact : max(known, incomePlan)
    }

    var essentialsForecast: Double {
        isComplete ? essentialsFact : essentialsFact + essentialsExpected
    }

    /// Свободные: берём худший из двух прогнозов — по темпу трат и по известным списаниям.
    var flexibleForecast: Double {
        if isComplete { return flexibleFact }
        return max(flexibleProjected, flexibleFact + flexibleExpected)
    }

    var savingsForecast: Double {
        incomeForecast - essentialsForecast - flexibleForecast
    }

    // MARK: Отклонения (плюс — в нашу пользу)

    var incomeDelta: Double { incomeForecast - incomePlan }
    var essentialsDelta: Double { essentialsPlan - essentialsForecast }
    var flexibleDelta: Double { flexibleLimit - flexibleForecast }
    var savingsDelta: Double { savingsForecast - savingsPlan }

    /// Обязательные ещё не покрыты известными операциями — рано объявлять экономию.
    var essentialsUnderCovered: Bool {
        !isComplete && essentialsPlan > 0 && essentialsForecast < essentialsPlan * 0.95
    }

    var hasPlan: Bool { incomePlan > 0 || essentialsPlan > 0 || savingsPlan > 0 }

    /// Можно ли доверять итогу. Пока обязательные расходы не покрыты ни фактом,
    /// ни ожиданиями по шаблонам, «лучше плана» — это иллюзия неполных данных.
    var isReliable: Bool { !essentialsUnderCovered }

    /// Общая зона месяца — отдельно от зоны лимита свободных трат.
    var zone: Zone {
        if savingsForecast <= 0 { return .danger }
        if savingsDelta < 0 { return .warning }
        return .safe
    }

    /// Одна фраза, объясняющая взаимозачёт: ради неё всё и считается.
    func verdict(currency: String) -> String {
        let overspend = -flexibleDelta
        let saved = essentialsDelta

        var parts: [String] = []

        if overspend > 1 && saved > 1 {
            parts.append("Перерасход свободных \(Fmt.money(overspend, code: currency)) частично покрыт тем, что обязательные выходят на \(Fmt.money(saved, code: currency)) дешевле плана.")
        } else if overspend > 1 {
            parts.append("Свободные траты выходят за лимит на \(Fmt.money(overspend, code: currency)).")
        } else if saved > 1 {
            parts.append("Обязательные выходят на \(Fmt.money(saved, code: currency)) дешевле плана, свободные — в рамках.")
        } else if saved < -1 {
            parts.append("Обязательные выходят на \(Fmt.money(-saved, code: currency)) дороже плана.")
        } else {
            parts.append("Месяц идёт по плану.")
        }

        if savingsDelta >= 1 {
            parts.append("В итоге накопления за месяц будут на \(Fmt.money(savingsDelta, code: currency)) больше плана.")
        } else if savingsDelta <= -1 {
            parts.append("В итоге накопления за месяц будут на \(Fmt.money(-savingsDelta, code: currency)) меньше плана.")
        } else {
            parts.append("На итог накоплений это почти не влияет.")
        }

        if overspend > 1 && savingsDelta >= 0 {
            parts.append("Лимит всё равно стоит вернуть в рамки: экономия на обязательных разовая, а привычка тратить — нет.")
        }

        if essentialsUnderCovered {
            parts.append("Месяц ещё не закончился и часть обязательных расходов может быть впереди — заведите на них регулярные шаблоны, тогда прогноз станет точным.")
        }

        return parts.joined(separator: " ")
    }
}

extension Analytics {

    /// Ожидаемое до конца месяца по регулярным шаблонам, разложенное по видам.
    var expectedRemainder: (income: Double, essential: Double, flexible: Double) {
        let month = currentMonth
        let entries = RecurrenceEngine.upcoming(rules: data.recurring, now: today, through: month.endDate)

        var income = 0.0
        var essential = 0.0
        var flexible = 0.0
        let map = categoryByID

        for entry in entries {
            let rule = entry.rule
            if rule.flow == .income {
                income += rule.amount
                continue
            }
            let kind = rule.categoryID.flatMap { map[$0]?.kind } ?? .flexible
            if kind == .essential {
                essential += rule.amount
            } else {
                flexible += rule.amount
            }
        }
        return (income, essential, flexible)
    }

    /// Свод текущего месяца: план, факт, ожидаемое и итог.
    var planFact: MonthPlanFact {
        let month = currentMonth
        let stats = thisMonth
        let status = budgetStatus
        let expected = expectedRemainder

        return MonthPlanFact(
            month: month,
            dayProgress: status.monthProgress,
            isComplete: status.monthProgress >= 0.999,
            incomePlan: profile.plannedIncome,
            incomeFact: stats.income,
            incomeExpected: expected.income,
            essentialsPlan: profile.essentialsPlan,
            essentialsFact: stats.essential,
            essentialsExpected: expected.essential,
            flexibleLimit: profile.flexibleLimit,
            flexibleFact: stats.flexible,
            flexibleExpected: expected.flexible,
            flexibleProjected: status.projected,
            savingsPlan: profile.savingsPlan
        )
    }
}
