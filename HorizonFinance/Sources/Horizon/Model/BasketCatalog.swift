import Foundation

/// Справочник корзины: страны, города, сети и товары.
///
/// Важно про цены: это **модель-ориентир**, а не выгрузка из магазинов.
/// Базовая цена — типичная испанская полка, дальше она множится на уровень города
/// и на уровень сети по категории. Любая цена, введённая руками в приложении,
/// перебивает модель и хранится в данных пользователя.
enum BasketCatalog {

    /// Когда справочник последний раз пересматривали руками.
    static let updatedAt = "февраль 2026"

    // MARK: Страны и города

    static let countries: [BasketCountry] = [spain, portugal, italy, france, germany, netherlands]

    static func country(id: String) -> BasketCountry {
        countries.first(where: { $0.id == id }) ?? spain
    }

    static func city(countryID: String, cityID: String) -> BasketCity {
        let target = country(id: countryID)
        return target.cities.first(where: { $0.id == cityID }) ?? target.cities[0]
    }

    /// Сети, которые действительно работают в этом городе.
    static func availableChains(countryID: String, cityID: String) -> [StoreChain] {
        let target = country(id: countryID)
        let resolved = target.cities.contains(where: { $0.id == cityID }) ? cityID : (target.cities.first?.id ?? "")
        let available = target.chains.filter { $0.isAvailable(in: resolved) }
        return available.isEmpty ? target.chains : available
    }

    static let spain = BasketCountry(
        id: "ES",
        name: "Испания",
        currencyCode: "EUR",
        cities: [
            BasketCity(id: "madrid", name: "Мадрид", index: 1.06),
            BasketCity(id: "barcelona", name: "Барселона", index: 1.09),
            BasketCity(id: "valencia", name: "Валенсия", index: 0.98),
            BasketCity(id: "sevilla", name: "Севилья", index: 0.95),
            BasketCity(id: "malaga", name: "Малага", index: 1.00),
            BasketCity(id: "alicante", name: "Аликанте", index: 0.97),
            // Страна Басков — один из самых дорогих регионов по продуктам.
            BasketCity(id: "bilbao", name: "Бильбао", index: 1.07),
            BasketCity(id: "zaragoza", name: "Сарагоса", index: 0.96),
            BasketCity(id: "murcia", name: "Мурсия", index: 0.94),
            BasketCity(id: "palma", name: "Пальма-де-Майорка", index: 1.12),
            BasketCity(id: "laspalmas", name: "Лас-Пальмас", index: 1.02)
        ],
        chains: [
            StoreChain(id: "es_mercadona", name: "Mercadona", baseIndex: 0.98,
                       categoryIndex: [.meat: 0.95, .produce: 1.02, .grocery: 0.97,
                                       .household: 0.95, .baby: 0.97, .drinks: 0.96]),
            StoreChain(id: "es_lidl", name: "Lidl", baseIndex: 0.92,
                       categoryIndex: [.dairy: 0.85, .grocery: 0.88, .produce: 1.00,
                                       .meat: 1.02, .household: 0.93, .drinks: 0.90, .baby: 1.05]),
            StoreChain(id: "es_aldi", name: "Aldi", baseIndex: 0.93,
                       categoryIndex: [.dairy: 0.87, .grocery: 0.90, .produce: 0.98,
                                       .meat: 1.03, .baby: 1.06]),
            StoreChain(id: "es_dia", name: "Dia", baseIndex: 0.96,
                       categoryIndex: [.baby: 0.92, .produce: 0.99, .meat: 1.00]),
            StoreChain(id: "es_carrefour", name: "Carrefour", baseIndex: 1.03,
                       categoryIndex: [.baby: 0.94, .household: 0.96, .drinks: 0.97, .produce: 1.05]),
            StoreChain(id: "es_alcampo", name: "Alcampo", baseIndex: 0.97,
                       categoryIndex: [.meat: 0.93, .produce: 0.96, .household: 0.94]),
            // Consum — кооператив Леванта: Валенсия, Аликанте, Мурсия, Каталония.
            StoreChain(id: "es_consum", name: "Consum", baseIndex: 1.01,
                       categoryIndex: [.produce: 0.97, .meat: 0.99],
                       cityIDs: ["valencia", "alicante", "murcia", "barcelona"]),
            // Eroski — баскский кооператив: север, Балеары, Каталония.
            StoreChain(id: "es_eroski", name: "Eroski", baseIndex: 1.01,
                       categoryIndex: [.meat: 0.96, .produce: 0.99, .household: 0.98,
                                       .baby: 0.97, .dairy: 1.00],
                       cityIDs: ["bilbao", "zaragoza", "barcelona", "palma", "madrid"]),
            // BM (Uvesco) — Страна Басков и север, сильная свежая полка.
            StoreChain(id: "es_bm", name: "BM Supermercados", baseIndex: 1.04,
                       categoryIndex: [.meat: 0.98, .produce: 0.98, .dairy: 1.03, .grocery: 1.06],
                       cityIDs: ["bilbao"]),
            StoreChain(id: "es_corteingles", name: "El Corte Inglés", baseIndex: 1.26,
                       categoryIndex: [.produce: 1.18, .meat: 1.20])
        ]
    )

    static let portugal = BasketCountry(
        id: "PT",
        name: "Португалия",
        currencyCode: "EUR",
        cities: [
            BasketCity(id: "lisboa", name: "Лиссабон", index: 1.02),
            BasketCity(id: "porto", name: "Порту", index: 0.96),
            BasketCity(id: "faro", name: "Фару", index: 0.98),
            BasketCity(id: "braga", name: "Брага", index: 0.93)
        ],
        chains: [
            StoreChain(id: "pt_continente", name: "Continente", baseIndex: 1.00,
                       categoryIndex: [.household: 0.97]),
            StoreChain(id: "pt_pingodoce", name: "Pingo Doce", baseIndex: 1.02,
                       categoryIndex: [.dairy: 0.98]),
            StoreChain(id: "pt_lidl", name: "Lidl", baseIndex: 0.90,
                       categoryIndex: [.dairy: 0.86, .grocery: 0.88]),
            StoreChain(id: "pt_auchan", name: "Auchan", baseIndex: 0.99,
                       categoryIndex: [.meat: 0.96]),
            StoreChain(id: "pt_minipreco", name: "Minipreço", baseIndex: 0.95)
        ]
    )

    static let italy = BasketCountry(
        id: "IT",
        name: "Италия",
        currencyCode: "EUR",
        cities: [
            BasketCity(id: "milano", name: "Милан", index: 1.16),
            BasketCity(id: "roma", name: "Рим", index: 1.10),
            BasketCity(id: "torino", name: "Турин", index: 1.05),
            BasketCity(id: "napoli", name: "Неаполь", index: 0.98),
            BasketCity(id: "bologna", name: "Болонья", index: 1.08)
        ],
        chains: [
            StoreChain(id: "it_esselunga", name: "Esselunga", baseIndex: 1.02),
            StoreChain(id: "it_coop", name: "Coop", baseIndex: 1.00,
                       categoryIndex: [.produce: 0.97]),
            StoreChain(id: "it_conad", name: "Conad", baseIndex: 0.99),
            StoreChain(id: "it_lidl", name: "Lidl", baseIndex: 0.89,
                       categoryIndex: [.dairy: 0.86, .grocery: 0.87]),
            StoreChain(id: "it_carrefour", name: "Carrefour", baseIndex: 1.05)
        ]
    )

    static let france = BasketCountry(
        id: "FR",
        name: "Франция",
        currencyCode: "EUR",
        cities: [
            BasketCity(id: "paris", name: "Париж", index: 1.28),
            BasketCity(id: "lyon", name: "Лион", index: 1.15),
            BasketCity(id: "marseille", name: "Марсель", index: 1.10),
            BasketCity(id: "toulouse", name: "Тулуза", index: 1.09),
            BasketCity(id: "nice", name: "Ницца", index: 1.18)
        ],
        chains: [
            StoreChain(id: "fr_leclerc", name: "E.Leclerc", baseIndex: 0.95,
                       categoryIndex: [.grocery: 0.92]),
            StoreChain(id: "fr_intermarche", name: "Intermarché", baseIndex: 0.98),
            StoreChain(id: "fr_lidl", name: "Lidl", baseIndex: 0.90,
                       categoryIndex: [.dairy: 0.87]),
            StoreChain(id: "fr_carrefour", name: "Carrefour", baseIndex: 1.03),
            StoreChain(id: "fr_monoprix", name: "Monoprix", baseIndex: 1.22)
        ]
    )

    static let germany = BasketCountry(
        id: "DE",
        name: "Германия",
        currencyCode: "EUR",
        cities: [
            BasketCity(id: "berlin", name: "Берлин", index: 1.08),
            BasketCity(id: "munchen", name: "Мюнхен", index: 1.20),
            BasketCity(id: "hamburg", name: "Гамбург", index: 1.12),
            BasketCity(id: "koln", name: "Кёльн", index: 1.09),
            BasketCity(id: "leipzig", name: "Лейпциг", index: 1.00)
        ],
        chains: [
            StoreChain(id: "de_aldi", name: "Aldi", baseIndex: 0.88,
                       categoryIndex: [.dairy: 0.85, .grocery: 0.86]),
            StoreChain(id: "de_lidl", name: "Lidl", baseIndex: 0.89,
                       categoryIndex: [.dairy: 0.86]),
            StoreChain(id: "de_rewe", name: "Rewe", baseIndex: 1.04),
            StoreChain(id: "de_edeka", name: "Edeka", baseIndex: 1.06,
                       categoryIndex: [.produce: 1.02]),
            StoreChain(id: "de_kaufland", name: "Kaufland", baseIndex: 0.97)
        ]
    )

    static let netherlands = BasketCountry(
        id: "NL",
        name: "Нидерланды",
        currencyCode: "EUR",
        cities: [
            BasketCity(id: "amsterdam", name: "Амстердам", index: 1.22),
            BasketCity(id: "rotterdam", name: "Роттердам", index: 1.14),
            BasketCity(id: "utrecht", name: "Утрехт", index: 1.16),
            BasketCity(id: "eindhoven", name: "Эйндховен", index: 1.12)
        ],
        chains: [
            StoreChain(id: "nl_ah", name: "Albert Heijn", baseIndex: 1.08),
            StoreChain(id: "nl_jumbo", name: "Jumbo", baseIndex: 1.02),
            StoreChain(id: "nl_lidl", name: "Lidl", baseIndex: 0.90,
                       categoryIndex: [.dairy: 0.87]),
            StoreChain(id: "nl_aldi", name: "Aldi", baseIndex: 0.89),
            StoreChain(id: "nl_dirk", name: "Dirk", baseIndex: 0.94)
        ]
    )

    // MARK: Товары

    static let products: [BasketProduct] = [
        // Молочное и яйца
        BasketProduct(id: "milk", name: "Молоко", unit: "1 л", category: .dairy,
                      basePrice: 0.95, perAdult: 7, perChild: 9),
        BasketProduct(id: "yogurt", name: "Йогурт натуральный", unit: "уп. 4×125 г", category: .dairy,
                      basePrice: 1.35, perAdult: 3, perChild: 5),
        BasketProduct(id: "cheese", name: "Сыр полутвёрдый", unit: "200 г", category: .dairy,
                      basePrice: 2.60, perAdult: 2.4, perChild: 1.8),
        BasketProduct(id: "kefir", name: "Кефир и творог", unit: "500 г", category: .dairy,
                      basePrice: 1.60, perAdult: 2, perChild: 2),
        BasketProduct(id: "butter", name: "Сливочное масло", unit: "250 г", category: .dairy,
                      basePrice: 2.40, perAdult: 0.8, perChild: 0.5),
        BasketProduct(id: "eggs", name: "Яйца", unit: "уп. 12 шт", category: .dairy,
                      basePrice: 2.60, perAdult: 2, perChild: 1.4),

        // Мясо и рыба
        BasketProduct(id: "chicken", name: "Куриное филе", unit: "кг", category: .meat,
                      basePrice: 6.50, perAdult: 2, perChild: 1),
        BasketProduct(id: "pork", name: "Свинина", unit: "кг", category: .meat,
                      basePrice: 6.90, perAdult: 1, perChild: 0.4),
        BasketProduct(id: "beefmince", name: "Фарш говяжий", unit: "кг", category: .meat,
                      basePrice: 8.90, perAdult: 0.8, perChild: 0.5),
        BasketProduct(id: "fish", name: "Рыба (хек, лосось)", unit: "кг", category: .meat,
                      basePrice: 9.50, perAdult: 0.8, perChild: 0.4),
        BasketProduct(id: "sausage", name: "Колбаса и сосиски", unit: "300 г", category: .meat,
                      basePrice: 3.20, perAdult: 1.5, perChild: 1),
        BasketProduct(id: "ham", name: "Ветчина нарезка", unit: "100 г", category: .meat,
                      basePrice: 1.90, perAdult: 2, perChild: 1.5),

        // Овощи и фрукты
        BasketProduct(id: "potato", name: "Картофель", unit: "кг", category: .produce,
                      basePrice: 1.20, perAdult: 3, perChild: 1.5),
        BasketProduct(id: "tomato", name: "Помидоры", unit: "кг", category: .produce,
                      basePrice: 2.10, perAdult: 2, perChild: 1),
        BasketProduct(id: "cucumber", name: "Огурцы", unit: "кг", category: .produce,
                      basePrice: 1.60, perAdult: 1, perChild: 0.6),
        BasketProduct(id: "onion", name: "Лук", unit: "кг", category: .produce,
                      basePrice: 1.30, perAdult: 1, perChild: 0.3),
        BasketProduct(id: "carrot", name: "Морковь", unit: "кг", category: .produce,
                      basePrice: 1.10, perAdult: 1, perChild: 0.6),
        BasketProduct(id: "salad", name: "Салат и зелень", unit: "упаковка", category: .produce,
                      basePrice: 1.30, perAdult: 2, perChild: 0.5),
        BasketProduct(id: "banana", name: "Бананы", unit: "кг", category: .produce,
                      basePrice: 1.60, perAdult: 1.5, perChild: 2),
        BasketProduct(id: "apple", name: "Яблоки", unit: "кг", category: .produce,
                      basePrice: 1.90, perAdult: 1.5, perChild: 2),
        BasketProduct(id: "orange", name: "Апельсины", unit: "кг", category: .produce,
                      basePrice: 1.40, perAdult: 2, perChild: 1.5),
        BasketProduct(id: "frozenveg", name: "Овощи замороженные", unit: "1 кг", category: .produce,
                      basePrice: 2.20, perAdult: 1, perChild: 0.8),

        // Бакалея
        BasketProduct(id: "bread", name: "Хлеб", unit: "буханка", category: .grocery,
                      basePrice: 1.10, perAdult: 8, perChild: 5),
        BasketProduct(id: "rice", name: "Рис", unit: "1 кг", category: .grocery,
                      basePrice: 1.40, perAdult: 1, perChild: 0.6),
        BasketProduct(id: "pasta", name: "Паста", unit: "500 г", category: .grocery,
                      basePrice: 1.05, perAdult: 2, perChild: 1.5),
        BasketProduct(id: "flour", name: "Мука", unit: "1 кг", category: .grocery,
                      basePrice: 0.85, perAdult: 0.5, perChild: 0.3),
        BasketProduct(id: "sugar", name: "Сахар", unit: "1 кг", category: .grocery,
                      basePrice: 1.20, perAdult: 0.4, perChild: 0.3),
        BasketProduct(id: "oliveoil", name: "Оливковое масло", unit: "1 л", category: .grocery,
                      basePrice: 7.90, perAdult: 0.8, perChild: 0.3),
        BasketProduct(id: "tuna", name: "Тунец консервированный", unit: "уп. 3 шт", category: .grocery,
                      basePrice: 2.80, perAdult: 1.5, perChild: 0.6),
        BasketProduct(id: "oats", name: "Овсянка и хлопья", unit: "500 г", category: .grocery,
                      basePrice: 1.30, perAdult: 1, perChild: 1.5),
        BasketProduct(id: "coffee", name: "Кофе молотый", unit: "250 г", category: .grocery,
                      basePrice: 3.20, perAdult: 1, perChild: 0),
        BasketProduct(id: "tea", name: "Чай", unit: "20 пакетиков", category: .grocery,
                      basePrice: 1.60, perAdult: 0.6, perChild: 0.2),
        BasketProduct(id: "sweets", name: "Печенье и сладкое", unit: "упаковка", category: .grocery,
                      basePrice: 2.20, perAdult: 2, perChild: 3),
        BasketProduct(id: "sauces", name: "Соусы и специи", unit: "упаковка", category: .grocery,
                      basePrice: 1.90, perAdult: 1.5, perChild: 0.4),

        // Напитки
        BasketProduct(id: "water", name: "Вода питьевая", unit: "уп. 6×1,5 л", category: .drinks,
                      basePrice: 2.40, perAdult: 1.5, perChild: 1),
        BasketProduct(id: "juice", name: "Сок", unit: "1 л", category: .drinks,
                      basePrice: 1.30, perAdult: 1.5, perChild: 3),

        // Бытовое и гигиена
        BasketProduct(id: "detergent", name: "Стиральный порошок", unit: "уп. ~20 стирок", category: .household,
                      basePrice: 5.50, perAdult: 0.4, perChild: 0.5),
        BasketProduct(id: "shower", name: "Гель для душа", unit: "600 мл", category: .household,
                      basePrice: 2.30, perAdult: 0.8, perChild: 0.6),
        BasketProduct(id: "shampoo", name: "Шампунь", unit: "400 мл", category: .household,
                      basePrice: 2.60, perAdult: 0.6, perChild: 0.4),
        BasketProduct(id: "toiletpaper", name: "Туалетная бумага", unit: "8 рулонов", category: .household,
                      basePrice: 3.90, perAdult: 0.7, perChild: 0.4),
        BasketProduct(id: "toothpaste", name: "Зубная паста", unit: "тюбик", category: .household,
                      basePrice: 2.10, perAdult: 0.5, perChild: 0.5),
        BasketProduct(id: "dishsoap", name: "Средство для посуды", unit: "флакон", category: .household,
                      basePrice: 1.60, perAdult: 0.5, perChild: 0.2),
        BasketProduct(id: "trashbags", name: "Мусорные пакеты", unit: "20 шт", category: .household,
                      basePrice: 1.50, perAdult: 0.5, perChild: 0.3),
        BasketProduct(id: "cleaner", name: "Средства для уборки", unit: "флакон", category: .household,
                      basePrice: 2.40, perAdult: 0.6, perChild: 0.3),

        // Детское
        BasketProduct(id: "diapers", name: "Подгузники", unit: "уп. 30–40 шт", category: .baby,
                      basePrice: 8.50, perAdult: 0, perChild: 4, onlyForAges: [.infant]),
        BasketProduct(id: "wipes", name: "Влажные салфетки", unit: "уп. 3 пачки", category: .baby,
                      basePrice: 2.40, perAdult: 0, perChild: 2, onlyForAges: [.infant, .preschool]),
        BasketProduct(id: "babyfood", name: "Детское пюре", unit: "уп. 4×100 г", category: .baby,
                      basePrice: 2.60, perAdult: 0, perChild: 8, onlyForAges: [.infant]),
        BasketProduct(id: "formula", name: "Детская смесь", unit: "800 г", category: .baby,
                      basePrice: 14.50, perAdult: 0, perChild: 1.5, onlyForAges: [.infant]),
        BasketProduct(id: "snacks", name: "Перекусы в школу", unit: "уп.", category: .baby,
                      basePrice: 2.20, perAdult: 0, perChild: 4, onlyForAges: [.preschool, .school])
    ]

    static func product(id: String) -> BasketProduct? {
        products.first(where: { $0.id == id })
    }
}
