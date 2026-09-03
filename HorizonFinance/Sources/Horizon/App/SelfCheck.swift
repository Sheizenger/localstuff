import Foundation

/// Проверка расчётной части без запуска интерфейса: `swift run Horizon --self-check`.
/// Пишет результат в консоль и завершается с кодом 1, если что-то посчиталось не так.
enum SelfCheck {

    static func runIfRequested() {
        guard CommandLine.arguments.contains("--self-check") else { return }
        let failures = run()
        if failures.isEmpty {
            print("\nВсе проверки пройдены.")
            exit(0)
        } else {
            print("\nПровалено проверок: \(failures.count)")
            exit(1)
        }
    }

    // MARK: Инструменты

    private static var failures: [String] = []

    private static func expect(_ condition: Bool, _ title: String, _ detail: String = "") {
        if condition {
            print("  ✓ \(title)")
        } else {
            failures.append(title)
            print("  ✗ \(title) \(detail)")
        }
    }

    private static func near(_ a: Double, _ b: Double, _ eps: Double = 0.01) -> Bool {
        abs(a - b) <= eps
    }

    private static func day(_ year: Int, _ month: Int, _ day: Int) -> Date {
        var parts = DateComponents()
        parts.year = year
        parts.month = month
        parts.day = day
        parts.hour = 12
        return Cal.ru.date(from: parts) ?? Date()
    }

    // MARK: Сценарии

    static func run() -> [String] {
        failures = []

        checkMonthKey()
        checkAnalytics()
        checkBudgetZones()
        checkForecastPriority()
        checkForecastShares()
        checkForecastMixed()
        checkMigration()
        checkFormatting()

        return failures
    }

    private static func checkMonthKey() {
        print("\nМесяцы:")
        let dec = MonthKey(year: 2025, month: 12)
        expect(dec.adding(1) == MonthKey(year: 2026, month: 1), "переход через год вперёд")
        expect(dec.adding(-12) == MonthKey(year: 2024, month: 12), "переход через год назад")
        expect(MonthKey.distance(from: MonthKey(year: 2025, month: 10), to: MonthKey(year: 2026, month: 3)) == 5,
               "расстояние между месяцами")
        expect(MonthKey(date: day(2026, 3, 31)) == MonthKey(year: 2026, month: 3), "месяц из даты")
        expect(MonthKey(year: 2026, month: 2).daysInMonth == 28, "дней в феврале 2026")
    }

    private static func makeSample() -> AppData {
        var data = AppData()
        let salary = Category(name: "Зарплата", emoji: "💼", flow: .income, kind: .essential)
        let rent = Category(name: "Аренда", emoji: "🏠", flow: .expense, kind: .essential)
        let fun = Category(name: "Кафе", emoji: "🍽", flow: .expense, kind: .flexible)
        data.categories = [salary, rent, fun]
        data.profile.currencyCode = "EUR"
        data.profile.openingBalance = 1000
        data.profile.flexibleLimit = 500

        func txn(_ amount: Double, _ cat: Category, _ date: Date) -> Txn {
            Txn(date: date, amount: amount, flow: cat.flow, categoryID: cat.id)
        }

        data.transactions = [
            // Январь: net = 4000 - 2000 - 500 = 1500
            txn(4000, salary, day(2026, 1, 5)),
            txn(2000, rent, day(2026, 1, 3)),
            txn(500, fun, day(2026, 1, 20)),
            // Февраль: net = 4000 - 2200 - 800 = 1000
            txn(4000, salary, day(2026, 2, 5)),
            txn(2200, rent, day(2026, 2, 3)),
            txn(800, fun, day(2026, 2, 18)),
            // Март (текущий, неполный)
            txn(4000, salary, day(2026, 3, 5)),
            txn(200, fun, day(2026, 3, 10))
        ]
        return data
    }

    private static func checkAnalytics() {
        print("\nАналитика:")
        var data = makeSample()
        let today = day(2026, 3, 15)

        let jan = Analytics(data: data, today: today).stats(for: MonthKey(year: 2026, month: 1))
        expect(near(jan.net, 1500), "чистый остаток января", "получилось \(jan.net)")
        expect(near(jan.essential, 2000) && near(jan.flexible, 500), "разделение обязательных и свободных")

        let completed = Analytics(data: data, today: today).completedMonths.filter { $0.hasData }
        expect(completed.count == 2, "текущий месяц не попадает в базу темпа", "месяцев: \(completed.count)")

        data.profile.paceMode = .lastMonth
        expect(near(Analytics(data: data, today: today).pace.value, 1000), "темп по последнему месяцу")

        data.profile.paceMode = .avg3
        expect(near(Analytics(data: data, today: today).pace.value, 1250), "средний темп за 3 месяца")

        data.profile.paceMode = .weighted
        // Веса свежих месяцев больше: (1500 * 2 + 1000 * 3) / 5 = 1200
        expect(near(Analytics(data: data, today: today).pace.value, 1200), "взвешенный темп")

        data.profile.paceMode = .manual
        data.profile.manualPace = 1750
        expect(near(Analytics(data: data, today: today).pace.value, 1750), "ручной темп")

        let a = Analytics(data: data, today: today)
        // 1000 + (12000 доходов) − (4200 обязательных) − (1500 свободных) = 7300
        expect(near(a.freeCash, 7300), "свободные деньги", "получилось \(a.freeCash)")

        let history = a.capitalHistory(months: 12)
        expect(history.last.map { near($0.value, 7300) } ?? false, "капитал на конец истории")
        expect(a.expenseBreakdown(month: MonthKey(year: 2026, month: 2)).first?.amount == 2200,
               "самая большая категория февраля")
    }

    private static func checkBudgetZones() {
        print("\nЗоны бюджета:")
        var data = makeSample()
        data.profile.flexibleLimit = 500
        let fun = data.categories.first(where: { $0.kind == .flexible })!
        let today = day(2026, 4, 15)

        func status(spent: Double) -> BudgetStatus {
            var copy = data
            copy.transactions = [Txn(date: day(2026, 4, 10), amount: spent, flow: .expense, categoryID: fun.id)]
            return Analytics(data: copy, today: today).budgetStatus
        }

        expect(status(spent: 150).zone == .safe, "150 из 500 к середине месяца — зелёная")
        expect(status(spent: 400).zone == .warning, "400 из 500 — жёлтая")
        expect(status(spent: 470).zone == .danger, "470 из 500 — красная")
        expect(status(spent: 600).zone == .danger, "перерасход — красная")
        expect(near(status(spent: 200).projected, 400, 15), "прогноз на конец месяца удваивает половину месяца")
    }

    private static func checkForecastPriority() {
        print("\nПрогноз, цели в очереди:")
        let now = day(2026, 1, 1)
        let first = Goal(title: "Подушка", targetAmount: 1000, priority: 0, funding: .queued)
        let second = Goal(title: "Машина", targetAmount: 500, priority: 1, funding: .queued)

        let result = Forecaster.build(goals: [first, second], pace: 250, savedFor: { _ in 0 }, now: now)
        expect(result.count == 2, "прогноз по двум целям")
        expect(near(result[0].months ?? -1, 4), "первая цель закрывается за 4 месяца")
        expect(near(result[1].months ?? -1, 6), "вторая стартует после первой и закрывается на 6-м месяце")
        expect(near(result[0].monthly, 250) && near(result[1].monthly, 0), "весь темп идёт в верхнюю цель")
        expect(result[1].isQueued, "вторая цель помечена как ожидающая")

        let zeroPace = Forecaster.build(goals: [first], pace: 0, savedFor: { _ in 0 }, now: now)
        expect(zeroPace[0].months == nil, "при нулевом темпе срок не определён")
        expect(zeroPace[0].unfundedReason != nil, "объяснение вместо срока")

        let done = Forecaster.build(goals: [first], pace: 250, savedFor: { _ in 1200 }, now: now)
        expect(done[0].isDone && near(done[0].progress, 1), "перевыполненная цель закрыта")
    }

    private static func checkForecastShares() {
        print("\nПрогноз, параллельные цели:")
        let now = day(2026, 1, 1)
        let a = Goal(title: "A", targetAmount: 1000, priority: 0, share: 0.5, funding: .parallel)
        let b = Goal(title: "B", targetAmount: 500, priority: 1, share: 0.5, funding: .parallel)

        let result = Forecaster.build(goals: [a, b], pace: 250, savedFor: { _ in 0 }, now: now)
        expect(near(result[0].monthly, 125) && near(result[1].monthly, 125), "темп делится поровну")
        expect(near(result[0].months ?? -1, 8), "цель A закрывается за 8 месяцев")
        expect(near(result[1].months ?? -1, 4), "цель B закрывается за 4 месяца")

        // Сумма долей больше 100% — нормируем, а не раздаём лишнего.
        let big1 = Goal(title: "A", targetAmount: 1000, priority: 0, share: 1.0, funding: .parallel)
        let big2 = Goal(title: "B", targetAmount: 1000, priority: 1, share: 1.0, funding: .parallel)
        let normalized = Forecaster.build(goals: [big1, big2], pace: 200, savedFor: { _ in 0 }, now: now)
        let total = normalized.reduce(0.0) { $0 + $1.monthly }
        expect(near(total, 200), "сумма распределений не превышает темп", "получилось \(total)")

        // Доля 0% — цель не финансируется, и это честно сообщается.
        let idle = Goal(title: "C", targetAmount: 500, priority: 0, share: 0, funding: .parallel)
        let idleResult = Forecaster.build(goals: [idle], pace: 300, savedFor: { _ in 0 }, now: now)
        expect(idleResult[0].months == nil && idleResult[0].unfundedReason != nil, "нулевая доля не даёт срока")

        // Дедлайн: нужно 1000 за ~6 месяцев, а темп даёт только 100 в месяц.
        let deadline = Cal.ru.date(byAdding: .month, value: 6, to: now)!
        let tight = Goal(title: "C", targetAmount: 1000, deadline: deadline, priority: 0, share: 1.0, funding: .parallel)
        let tightResult = Forecaster.build(goals: [tight], pace: 100, savedFor: { _ in 0 }, now: now)
        expect((tightResult[0].deadlineSlack ?? 0) < 0, "опоздание к дедлайну определяется")
        expect(tightResult[0].deadlineZone == .danger, "красная метка по дедлайну")
        expect(near(tightResult[0].requiredMonthly ?? 0, 1000 / 6.0, 5), "нужный ежемесячный взнос")
    }

    /// Главный сценарий: две цели копятся параллельно, третья ждёт очереди
    /// и подхватывает всё, что осталось, — включая долю закрывшейся цели.
    private static func checkForecastMixed() {
        print("\nПрогноз, смешанный режим:")
        let now = day(2026, 1, 1)
        let a = Goal(title: "A", targetAmount: 1000, priority: 0, share: 0.5, funding: .parallel)
        let b = Goal(title: "B", targetAmount: 500, priority: 1, share: 0.5, funding: .parallel)
        let c = Goal(title: "C", targetAmount: 300, priority: 2, funding: .queued)

        let result = Forecaster.build(goals: [a, b, c], pace: 250, savedFor: { _ in 0 }, now: now)
        expect(result.count == 3, "прогноз по трём целям")
        expect(near(result[0].monthly, 125) && near(result[1].monthly, 125),
               "параллельные цели забирают свои доли сразу")
        expect(near(result[2].monthly, 0) && result[2].isQueued,
               "очередной цели сейчас не достаётся ничего")

        expect(near(result[1].months ?? -1, 4), "B (500 по 125) закрывается за 4 месяца")
        expect(near(result[0].months ?? -1, 8), "A (1000 по 125) закрывается за 8 месяцев")
        // После закрытия B её 125 уходят в очередь: C получает 125, 125 и 50 → 6.4 месяца.
        expect(near(result[2].months ?? -1, 6.4, 0.05),
               "C стартует на 5-м месяце и закрывается за 6.4",
               "получилось \(String(describing: result[2].months))")
        expect(near(result[2].startsInMonths, 4), "старт C — после закрытия B")

        // Ни один месяц не раздаёт больше, чем есть в темпе.
        let handedOut = result.reduce(0.0) { $0 + $1.monthly }
        expect(handedOut <= 250.0001, "в первый месяц роздано не больше темпа", "роздано \(handedOut)")

        // Если параллельных целей нет, очередь работает как раньше.
        let onlyQueue = Forecaster.build(goals: [c], pace: 250, savedFor: { _ in 0 }, now: now)
        expect(near(onlyQueue[0].monthly, 250), "без параллельных целей очередь берёт весь темп")
    }

    /// Файлы первой версии не знали про режим у цели — проверяем, что они читаются
    /// и что общий режим из профиля корректно переезжает в каждую цель.
    private static func checkMigration() {
        print("\nЧтение файлов первой версии:")

        func legacyJSON(mode: String) -> Data {
            let text = """
            {
              "schemaVersion": 1,
              "profile": {
                "currencyCode": "EUR", "openingBalance": 0, "plannedIncome": 0,
                "essentialsPlan": 0, "flexibleLimit": 400, "savingsPlan": 1000,
                "paceMode": "weighted", "manualPace": 1500, "fundingMode": "\(mode)"
              },
              "categories": [],
              "goals": [{
                "id": "1D8A9F3C-0000-4000-8000-000000000001",
                "title": "Подушка", "emoji": "🛟", "targetAmount": 10000,
                "startingAmount": 0, "priority": 0, "share": 0.6,
                "colorHex": "#2FBF71", "isArchived": false, "note": ""
              }],
              "transactions": [],
              "contributions": []
            }
            """
            return Data(text.utf8)
        }

        let decoder = Persistence.makeDecoder()

        if let shares = try? decoder.decode(AppData.self, from: legacyJSON(mode: "shares")) {
            expect(shares.goals.first?.funding == .parallel, "старый режим «долями» → параллельная цель")
            expect(shares.schemaVersion == 2, "версия схемы поднимается до 2")
            expect(near(shares.profile.flexibleLimit, 400), "остальные настройки на месте")
            expect(near(shares.goals.first?.share ?? 0, 0.6), "доля цели сохранилась")
        } else {
            expect(false, "старый файл с режимом «долями» читается")
        }

        if let priority = try? decoder.decode(AppData.self, from: legacyJSON(mode: "priority")) {
            expect(priority.goals.first?.funding == .queued, "старый режим «по очереди» → цель в очереди")
        } else {
            expect(false, "старый файл с режимом «по очереди» читается")
        }

        // Файл без единого знакомого поля не должен ронять приложение.
        if let empty = try? decoder.decode(AppData.self, from: Data("{}".utf8)) {
            expect(empty.goals.isEmpty && empty.transactions.isEmpty, "пустой файл читается без ошибок")
        } else {
            expect(false, "пустой файл читается без ошибок")
        }
    }

    private static func checkFormatting() {
        print("\nФорматирование:")
        expect(Fmt.monthsWord(1) == "1 месяц", "1 месяц")
        expect(Fmt.monthsWord(3) == "3 месяца", "3 месяца")
        expect(Fmt.monthsWord(11) == "11 месяцев", "11 месяцев")
        expect(Fmt.horizon(months: 15) == "1 год 3 месяца", "горизонт 15 месяцев", Fmt.horizon(months: 15))
        expect(Fmt.horizon(months: 24) == "2 года", "горизонт 24 месяца", Fmt.horizon(months: 24))
        expect(Fmt.horizon(months: 0.2) == "меньше месяца", "совсем короткий горизонт")
        expect(Fmt.horizon(months: 400) == "больше 15 лет", "слишком длинный горизонт")
        expect(Fmt.money(1234, code: "EUR").contains("€"), "символ валюты в сумме", Fmt.money(1234, code: "EUR"))
    }
}
