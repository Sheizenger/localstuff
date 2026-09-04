import Foundation

// MARK: - Категории корзины

enum BasketCategory: String, Codable, CaseIterable, Identifiable, Hashable {
    case dairy
    case meat
    case produce
    case grocery
    case drinks
    case household
    case baby

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dairy: return "Молочное и яйца"
        case .meat: return "Мясо и рыба"
        case .produce: return "Овощи и фрукты"
        case .grocery: return "Бакалея"
        case .drinks: return "Напитки"
        case .household: return "Бытовое и гигиена"
        case .baby: return "Детское"
        }
    }

    var emoji: String {
        switch self {
        case .dairy: return "🥛"
        case .meat: return "🍗"
        case .produce: return "🥦"
        case .grocery: return "🍝"
        case .drinks: return "🧃"
        case .household: return "🧴"
        case .baby: return "🍼"
        }
    }
}

/// Возраст ребёнка сильно меняет корзину: подгузники и смесь против школьных перекусов.
enum ChildAge: String, Codable, CaseIterable, Identifiable, Hashable {
    case infant
    case preschool
    case school

    var id: String { rawValue }

    var title: String {
        switch self {
        case .infant: return "0–2 года"
        case .preschool: return "3–6 лет"
        case .school: return "7–14 лет"
        }
    }

    var shortTitle: String {
        switch self {
        case .infant: return "малыш"
        case .preschool: return "дошкольник"
        case .school: return "школьник"
        }
    }

    /// Какую часть взрослой порции съедает ребёнок этого возраста.
    var factor: Double {
        switch self {
        case .infant: return 0.35
        case .preschool: return 0.6
        case .school: return 0.85
        }
    }
}

// MARK: - Справочник

struct BasketProduct: Identifiable, Hashable {
    let id: String
    let name: String
    /// Единица, в которой указана цена: «1 л», «кг», «упаковка 12 шт».
    let unit: String
    let category: BasketCategory
    /// Базовая цена — типичная полка в Испании, точка отсчёта для всей модели.
    let basePrice: Double
    /// Сколько единиц в месяц нужно одному взрослому.
    let perAdult: Double
    /// Сколько единиц в месяц нужно ребёнку (до поправки на возраст).
    let perChild: Double
    /// Если не пусто — товар нужен только при детях этого возраста.
    let onlyForAges: [ChildAge]

    init(
        id: String,
        name: String,
        unit: String,
        category: BasketCategory,
        basePrice: Double,
        perAdult: Double,
        perChild: Double,
        onlyForAges: [ChildAge] = []
    ) {
        self.id = id
        self.name = name
        self.unit = unit
        self.category = category
        self.basePrice = basePrice
        self.perAdult = perAdult
        self.perChild = perChild
        self.onlyForAges = onlyForAges
    }
}

struct StoreChain: Identifiable, Hashable {
    let id: String
    let name: String
    /// Общий уровень цен сети относительно базовой полки.
    let baseIndex: Double
    /// Где сеть заметно отличается от своего же среднего уровня.
    let categoryIndex: [BasketCategory: Double]
    /// Города, где сеть реально представлена. Пусто — сеть есть по всей стране.
    let cityIDs: [String]

    init(
        id: String,
        name: String,
        baseIndex: Double,
        categoryIndex: [BasketCategory: Double] = [:],
        cityIDs: [String] = []
    ) {
        self.id = id
        self.name = name
        self.baseIndex = baseIndex
        self.categoryIndex = categoryIndex
        self.cityIDs = cityIDs
    }

    func index(for category: BasketCategory) -> Double {
        categoryIndex[category] ?? baseIndex
    }

    func isAvailable(in cityID: String) -> Bool {
        cityIDs.isEmpty || cityIDs.contains(cityID)
    }

    /// Региональные сети подписываем, чтобы не выглядело, будто список городов случаен.
    var isRegional: Bool { !cityIDs.isEmpty }
}

struct BasketCity: Identifiable, Hashable {
    let id: String
    let name: String
    /// Уровень цен города к базовой полке — включая страновую разницу.
    let index: Double
}

struct BasketCountry: Identifiable, Hashable {
    let id: String
    let name: String
    let currencyCode: String
    let cities: [BasketCity]
    let chains: [StoreChain]
}

// MARK: - Состав семьи

struct Household: Hashable {
    var adults: Int = 2
    var children: [ChildAge] = []

    var peopleCount: Int { adults + children.count }

    var title: String {
        var parts: [String] = []
        parts.append(Fmt.peopleWord(adults))
        if !children.isEmpty {
            let kids = children.map { $0.shortTitle }.joined(separator: ", ")
            parts.append("+ \(kids)")
        }
        return parts.joined(separator: " ")
    }
}

// MARK: - Настройки раздела

struct BasketSettings: Codable, Hashable {
    var countryID: String = "ES"
    var cityID: String = "bilbao"
    var adults: Int = 2
    var infants: Int = 0
    var preschoolers: Int = 0
    var schoolers: Int = 0
    /// Пусто — считаем по всем сетям страны.
    var selectedChainIDs: [String] = []
    /// Ключ — «идСети|идТовара». Цена, введённая руками, всегда важнее модели.
    var priceOverrides: [String: Double] = [:]
    /// Товары, которые эта семья не покупает.
    var excludedProductIDs: [String] = []

    var household: Household {
        var children: [ChildAge] = []
        children.append(contentsOf: Array(repeating: ChildAge.infant, count: max(infants, 0)))
        children.append(contentsOf: Array(repeating: ChildAge.preschool, count: max(preschoolers, 0)))
        children.append(contentsOf: Array(repeating: ChildAge.school, count: max(schoolers, 0)))
        return Household(adults: max(adults, 1), children: children)
    }

    static func overrideKey(chainID: String, productID: String) -> String {
        "\(chainID)|\(productID)"
    }

    enum CodingKeys: String, CodingKey {
        case countryID, cityID, adults, infants, preschoolers, schoolers
        case selectedChainIDs, priceOverrides, excludedProductIDs
    }
}

extension BasketSettings {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var settings = BasketSettings()
        settings.countryID = try container.decodeIfPresent(String.self, forKey: .countryID) ?? "ES"
        settings.cityID = try container.decodeIfPresent(String.self, forKey: .cityID) ?? "bilbao"
        settings.adults = try container.decodeIfPresent(Int.self, forKey: .adults) ?? 2
        settings.infants = try container.decodeIfPresent(Int.self, forKey: .infants) ?? 0
        settings.preschoolers = try container.decodeIfPresent(Int.self, forKey: .preschoolers) ?? 0
        settings.schoolers = try container.decodeIfPresent(Int.self, forKey: .schoolers) ?? 0
        settings.selectedChainIDs = try container.decodeIfPresent([String].self, forKey: .selectedChainIDs) ?? []
        settings.priceOverrides = try container.decodeIfPresent([String: Double].self, forKey: .priceOverrides) ?? [:]
        settings.excludedProductIDs = try container.decodeIfPresent([String].self, forKey: .excludedProductIDs) ?? []
        self = settings
    }
}
