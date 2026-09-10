import Foundation

extension AppData {

    /// Стартовый набор: категории на русском и одна очевидная цель — подушка.
    static func starter() -> AppData {
        var data = AppData()
        data.categories = Category.defaults
        data.profile = Profile(
            currencyCode: "EUR",
            openingBalance: 0,
            plannedIncome: 0,
            essentialsPlan: 0,
            flexibleLimit: 400,
            savingsPlan: 1000,
            paceMode: .weighted,
            manualPace: 1500,
            fundingMode: .priority
        )
        data.goals = [
            Goal(
                title: "Подушка безопасности",
                emoji: "🛟",
                targetAmount: 10000,
                startingAmount: 0,
                deadline: nil,
                priority: 0,
                share: 0.6,
                colorHex: "#2FBF71",
                note: "Неприкосновенный минимум. Не тратится на машину, поездки и покупки для дома."
            )
        ]
        return data
    }

    /// Демо-данные: семь месяцев жизни после переезда, чтобы сразу увидеть графики и прогноз.
    static func demo(now: Date = Date()) -> AppData {
        var data = AppData()
        data.categories = Category.defaults
        data.profile = Profile(
            currencyCode: "EUR",
            // Накопленные 4 000 лежат в подушке, здесь — только текущий остаток на карте.
            openingBalance: 900,
            plannedIncome: 4200,
            essentialsPlan: 2200,
            flexibleLimit: 500,
            savingsPlan: 1500,
            paceMode: .weighted,
            manualPace: 1500,
            fundingMode: .priority
        )

        let cushion = Goal(
            title: "Подушка безопасности",
            emoji: "🛟",
            targetAmount: 10000,
            startingAmount: 4000,
            deadline: nil,
            priority: 0,
            share: 0.55,
            colorHex: "#2FBF71",
            note: "Сначала 10k, потом не трогаем."
        )
        let car = Goal(
            title: "Машина",
            emoji: "🚗",
            targetAmount: 9000,
            startingAmount: 0,
            deadline: Cal.ru.date(byAdding: .month, value: 14, to: now),
            priority: 1,
            share: 0.3,
            colorHex: "#4F8DF7",
            note: "Часть наличными, остаток — умеренное финансирование."
        )
        let home = Goal(
            title: "Первый взнос за жильё",
            emoji: "🏡",
            targetAmount: 45000,
            startingAmount: 0,
            deadline: nil,
            priority: 2,
            share: 0.15,
            colorHex: "#8E7CF0",
            note: "Длинная цель. Ипотеку считаем только по подтверждённому доходу."
        )
        data.goals = [cushion, car, home]

        func cat(_ name: String) -> UUID? {
            data.categories.first(where: { $0.name == name })?.id
        }

        var rng = SmallRandom(seed: 20260903)
        var txns: [Txn] = []
        var contributions: [Contribution] = []

        // Шесть завершённых месяцев + текущий, который ещё идёт.
        for back in stride(from: 6, through: 0, by: -1) {
            let month = MonthKey(date: now).adding(-back)
            let isCurrent = back == 0
            let dayLimit = isCurrent ? max(Cal.ru.component(.day, from: now), 1) : month.daysInMonth

            func day(_ d: Int) -> Date {
                let clamped = min(max(d, 1), dayLimit)
                var parts = DateComponents()
                parts.year = month.year
                parts.month = month.month
                parts.day = clamped
                parts.hour = 12
                return Cal.ru.date(from: parts) ?? month.startDate
            }

            func add(_ amount: Double, _ categoryName: String, _ flow: MoneyFlow, _ d: Int, _ note: String = "") {
                guard amount > 0 else { return }
                guard !isCurrent || d <= dayLimit else { return }
                txns.append(Txn(date: day(d), amount: (amount * 100).rounded() / 100,
                                flow: flow, categoryID: cat(categoryName), note: note))
            }

            // Доход
            add(4200 + rng.next(-120, 260), "Зарплата", .income, 5, "Зарплата")
            if back % 2 == 0 {
                add(rng.next(150, 480), "Подработка", .income, 18, "Проект")
            }

            // Обязательные
            add(1250, "Аренда", .expense, 3, "Квартира")
            add(rng.next(95, 190), "Коммуналка", .expense, 8)
            add(rng.next(420, 620), "Продукты", .expense, 6)
            add(rng.next(380, 560), "Продукты", .expense, 20)
            add(rng.next(45, 90), "Транспорт", .expense, 10)
            add(rng.next(25, 45), "Связь", .expense, 12)

            // Свободные — те самые «дыры» после переезда
            add(rng.next(60, 200), "Кафе и доставка", .expense, 7, "Доставка")
            add(rng.next(40, 160), "Кафе и доставка", .expense, 22)
            add(rng.next(30, 260), "Дом и обустройство", .expense, 14, "Мебель и мелочи")
            add(rng.next(20, 180), "Покупки", .expense, 16)
            add(rng.next(15, 40), "Подписки", .expense, 2)
            if back == 5 { add(640, "Документы", .expense, 11, "NIE, переводы, пошлины") }
            if back == 4 { add(430, "Здоровье", .expense, 19, "Стоматолог") }
            if back == 2 { add(720, "Поездки", .expense, 13, "Билеты домой") }
            if back == 1 { add(310, "Покупки", .expense, 24, "Ноутбучные аксессуары") }

            // Переводы в цели — не каждый месяц одинаково, как в жизни
            if !isCurrent {
                let moved = Double(Int(rng.next(700, 1400) / 50)) * 50
                contributions.append(Contribution(goalID: cushion.id, date: day(6),
                                                  amount: moved, note: "Перевод в день зарплаты"))
            } else {
                contributions.append(Contribution(goalID: cushion.id, date: day(6),
                                                  amount: 1000, note: "Перевод в день зарплаты"))
            }
        }

        data.transactions = txns.sorted { $0.date > $1.date }
        data.contributions = contributions.sorted { $0.date > $1.date }
        return data
    }
}

extension Category {
    static var defaults: [Category] {
        [
            Category(name: "Зарплата", emoji: "💼", flow: .income, kind: .essential),
            Category(name: "Подработка", emoji: "💻", flow: .income, kind: .essential),
            Category(name: "Прочий доход", emoji: "🎁", flow: .income, kind: .essential),

            Category(name: "Аренда", emoji: "🏠", flow: .expense, kind: .essential),
            Category(name: "Коммуналка", emoji: "💡", flow: .expense, kind: .essential),
            Category(name: "Продукты", emoji: "🛒", flow: .expense, kind: .essential),
            Category(name: "Транспорт", emoji: "🚇", flow: .expense, kind: .essential),
            Category(name: "Связь", emoji: "📱", flow: .expense, kind: .essential),
            Category(name: "Страховка", emoji: "🛡", flow: .expense, kind: .essential),
            Category(name: "Документы", emoji: "📄", flow: .expense, kind: .essential),

            Category(name: "Кафе и доставка", emoji: "🍽", flow: .expense, kind: .flexible),
            Category(name: "Покупки", emoji: "🛍", flow: .expense, kind: .flexible),
            Category(name: "Дом и обустройство", emoji: "🪑", flow: .expense, kind: .flexible),
            Category(name: "Здоровье", emoji: "💊", flow: .expense, kind: .flexible),
            Category(name: "Поездки", emoji: "✈️", flow: .expense, kind: .flexible),
            Category(name: "Подписки", emoji: "🎬", flow: .expense, kind: .flexible),
            Category(name: "Обучение", emoji: "🎓", flow: .expense, kind: .flexible),
            Category(name: "Прочее", emoji: "✨", flow: .expense, kind: .flexible)
        ]
    }
}

/// Простой воспроизводимый генератор — чтобы демо выглядело одинаково при каждом запуске.
struct SmallRandom {
    private var state: UInt64

    init(seed: UInt64) {
        state = seed &* 6364136223846793005 &+ 1442695040888963407
    }

    mutating func unit() -> Double {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let bits = (state >> 33) & 0xFFFFFF
        return Double(bits) / Double(0xFFFFFF)
    }

    mutating func next(_ lower: Double, _ upper: Double) -> Double {
        lower + unit() * (upper - lower)
    }
}
