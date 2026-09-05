import Foundation

/// Правило: если в назначении платежа встретилось слово — это такая-то категория.
struct MerchantRule {
    let keywords: [String]
    let categoryName: String
    /// Ограничение по направлению: зарплата — только доход.
    let flow: MoneyFlow?

    init(_ keywords: [String], _ categoryName: String, flow: MoneyFlow? = nil) {
        self.keywords = keywords
        self.categoryName = categoryName
        self.flow = flow
    }
}

/// Автокатегоризация строк банковской выписки по назначению платежа.
///
/// Список заточен под испанские банки: названия сетей, операторов и коммунальщиков
/// в выписке пишутся почти всегда одинаково.
enum MerchantRules {

    static let rules: [MerchantRule] = [
        MerchantRule(["nomina", "salario", "sueldo", "payroll"], "Зарплата", flow: .income),
        MerchantRule(["freelance", "factura emitida", "honorarios"], "Подработка", flow: .income),

        MerchantRule(["alquiler", "arrendamiento", "renta piso", "inmobiliaria"], "Аренда"),
        MerchantRule(["iberdrola", "endesa", "naturgy", "repsol luz", "holaluz", "totalenergies",
                      "agua", "consorcio de aguas", "gas natural", "comunidad de propietarios"], "Коммуналка"),
        MerchantRule(["movistar", "vodafone", "orange", "yoigo", "digi", "masmovil", "pepephone",
                      "jazztel", "euskaltel"], "Связь"),
        MerchantRule(["mapfre", "axa", "allianz", "seguro", "linea directa", "mutua"], "Страховка"),

        MerchantRule(["mercadona", "eroski", "bm supermercados", "lidl", "aldi", "carrefour",
                      "alcampo", "consum", "dia sa", "supermercado", "hipercor", "condis",
                      "caprabo", "froiz", "gadis"], "Продукты"),

        MerchantRule(["mcdonald", "burger king", "kfc", "telepizza", "domino", "goiko", "subway",
                      "five guys", "taco bell", "papa john", "glovo", "uber eats", "just eat",
                      "deliveroo", "kebab"], "Фаст-фуд"),
        MerchantRule(["restaurante", "cafeteria", "cafe ", "bar ", "taberna", "pizzeria",
                      "starbucks", "pasteleria", "panaderia bar"], "Кафе и доставка"),

        MerchantRule(["metro bilbao", "bizkaibus", "euskotren", "renfe", "alsa", "taxi", "cabify",
                      "uber trip", "bolt", "gasolinera", "repsol", "cepsa", "shell", "bp ",
                      "parking", "peaje", "bizkaibus"], "Транспорт"),

        MerchantRule(["farmacia", "clinica", "dentista", "hospital", "sanitas", "adeslas",
                      "optica", "laboratorio"], "Здоровье"),

        MerchantRule(["netflix", "spotify", "apple.com", "icloud", "hbo", "disney", "amazon prime",
                      "youtube premium", "google storage", "dropbox", "adobe", "openai",
                      "playstation", "xbox", "gimnasio", "gym"], "Подписки"),

        MerchantRule(["ikea", "leroy merlin", "bricomart", "conforama", "maisons du monde",
                      "ferreteria"], "Дом и обустройство"),

        MerchantRule(["amazon", "zara", "decathlon", "el corte ingles", "primark", "mediamarkt",
                      "fnac", "pull&bear", "bershka", "h&m", "sprinter", "aliexpress"], "Покупки"),

        MerchantRule(["ryanair", "vueling", "iberia", "booking", "airbnb", "renfe ave", "hotel",
                      "easyjet", "kayak", "skyscanner"], "Поездки"),

        MerchantRule(["extranjeria", "consulado", "tasa", "notaria", "registro civil",
                      "traduccion jurada", "gestoria"], "Документы"),

        MerchantRule(["udemy", "coursera", "escuela", "academia", "curso", "matricula"], "Обучение")
    ]

    /// Название категории для строки выписки или nil, если правило не нашлось.
    static func categoryName(for details: String, amount: Double) -> String? {
        let normalized = ProductMatcher.normalize(details)
        guard !normalized.isEmpty else { return nil }
        let flow: MoneyFlow = amount >= 0 ? .income : .expense

        var bestName: String? = nil
        var bestLength = 0

        for rule in rules {
            if let required = rule.flow, required != flow { continue }
            for keyword in rule.keywords {
                let needle = ProductMatcher.normalize(keyword)
                guard !needle.isEmpty, needle.count > bestLength else { continue }
                if normalized.contains(needle) {
                    bestLength = needle.count
                    bestName = rule.categoryName
                }
            }
        }
        return bestName
    }

    /// Ключ для запоминания ручного выбора пользователя.
    static func ruleKey(for details: String) -> String {
        let normalized = ProductMatcher.normalize(details)
        // Хвост выписки часто содержит номер операции — берём первые слова, они устойчивее.
        let words = normalized.split(separator: " ").prefix(4)
        return words.joined(separator: " ")
    }
}
