import Foundation

/// Узнаёт товар справочника по строке из чека.
///
/// Чеки печатают сокращённо и на местном языке («LECHE ENT SEMI 1L», «ESNEA»),
/// поэтому сопоставление идёт по ключевым словам, а всё, что пользователь поправил
/// руками, запоминается и в следующий раз срабатывает точно.
enum ProductMatcher {

    /// Ключевые слова по товарам: испанский, где уместно — баскский и английский.
    static let keywords: [String: [String]] = [
        // Молочное и яйца
        "milk": ["leche", "esne", "llet"],
        "yogurt": ["yogur", "yoghurt", "griego"],
        "cheese": ["queso", "gazta", "formatge", "mozzarella", "cheddar"],
        "kefir": ["kefir", "requeson", "quark", "cuajada"],
        "butter": ["mantequilla", "gurin"],
        "eggs": ["huevo", "arraultz"],

        // Мясо и рыба
        "chicken": ["pollo", "oilasko", "pechuga", "muslo"],
        "pork": ["cerdo", "lomo", "chuleta", "panceta", "secreto"],
        "beefmince": ["picada", "carne picada", "ternera", "vacuno", "hamburguesa"],
        "fish": ["merluza", "salmon", "bacalao", "lubina", "dorada", "atun fresco", "pescado", "gamba", "langostino"],
        "frozenfish": ["congelado", "varitas", "empanadilla", "pizza", "precocinado", "nuggets", "croqueta"],
        "sausage": ["salchicha", "chorizo", "morcilla", "txistorra", "fuet", "salchichon"],
        "ham": ["jamon", "pavo", "lonchas", "bacon", "mortadela"],

        // Овощи и фрукты
        "potato": ["patata", "patatas", "boniato"],
        "tomato": ["tomate"],
        "cucumber": ["pepino"],
        "onion": ["cebolla", "ajo", "puerro"],
        "carrot": ["zanahoria"],
        "pepper": ["pimiento", "calabacin", "berenjena", "calabaza"],
        "salad": ["lechuga", "ensalada", "canonigos", "rucula", "espinaca", "brocoli", "coliflor", "judia"],
        "banana": ["platano", "banana"],
        "apple": ["manzana", "pera"],
        "orange": ["naranja", "mandarina", "limon", "pomelo"],
        "berries": ["fresa", "arandano", "frambuesa", "uva", "kiwi", "melon", "sandia", "aguacate", "melocoton", "cereza"],
        "frozenveg": ["verdura congelada", "menestra", "guisantes congelados"],

        // Бакалея
        "bread": ["pan ", "barra", "hogaza", "chapata", "ogia", "baguette", "pan"],
        "rice": ["arroz"],
        "pasta": ["pasta", "macarron", "espagueti", "fideo", "tallarin"],
        "legumes": ["lenteja", "garbanzo", "alubia", "judias", "maiz", "tomate frito", "conserva"],
        "flour": ["harina"],
        "sugar": ["azucar"],
        "oliveoil": ["aceite", "oliva", "virgen extra"],
        "tuna": ["atun", "sardina", "mejillon", "berberecho"],
        "olives": ["aceituna", "oliva rellena", "encurtido", "banderilla"],
        "nuts": ["almendra", "nuez", "nueces", "anacardo", "pistacho", "frutos secos", "pasas"],
        "jam": ["mermelada", "miel", "confitura", "crema cacao", "nocilla", "nutella"],
        "chocolate": ["chocolate", "cacao", "bombon", "tableta"],
        "oats": ["avena", "copos"],
        "cereal": ["cereales", "muesli", "granola"],
        "coffee": ["cafe", "kafea", "capsula", "descafeinado"],
        "tea": ["te ", "infusion", "manzanilla", "poleo"],
        "sweets": ["galleta", "bolleria", "croissant", "magdalena", "bizcocho", "donut", "tarta", "helado"],
        "sauces": ["salsa", "mayonesa", "ketchup", "mostaza", "vinagre", "sal ", "especia", "pimienta", "caldo", "sofrito"],

        // Напитки
        "water": ["agua", "ura"],
        "juice": ["zumo", "nectar", "batido"],
        "soda": ["refresco", "cola", "gaseosa", "tonica", "fanta", "sprite", "aquarius", "nestea"],
        "alcohol": ["cerveza", "vino", "garagardo", "sidra", "rioja", "tinto", "blanco", "cava", "ron", "ginebra", "whisky"],

        // Бытовое и гигиена
        "detergent": ["detergente", "lavadora", "colada"],
        "softener": ["suavizante"],
        "shower": ["gel de ducha", "gel ducha", "jabon"],
        "shampoo": ["champu", "acondicionador", "mascarilla pelo"],
        "deodorant": ["desodorante"],
        "razors": ["cuchilla", "maquinilla", "espuma afeitar", "gillette"],
        "hygiene": ["compresa", "tampon", "salvaslip", "higiene intima", "crema hidratante", "protector"],
        "toiletpaper": ["papel higienico", "papel wc"],
        "toothpaste": ["dentifrico", "pasta de dientes", "cepillo dental", "colutorio", "enjuague"],
        "dishsoap": ["lavavajillas", "friegaplatos"],
        "cleaner": ["limpiador", "limpiahogar", "lejia", "amoniaco", "desinfectante", "multiusos"],
        "kitchenstuff": ["estropajo", "bayeta", "papel cocina", "aluminio", "film", "bolsa congelacion", "servilleta"],
        "trashbags": ["bolsa basura", "basura"],
        "pharmacy": ["farmacia", "vitamina", "ibuprofeno", "paracetamol", "tirita", "botiquin"],

        // Детское
        "diapers": ["panal", "dodot", "pañal"],
        "wipes": ["toallita"],
        "babyfood": ["potito", "papilla", "tarrito"],
        "formula": ["leche infantil", "formula infantil", "nutriben", "puleva bebe"],
        "snacks": ["snack", "barrita", "zumo infantil"]
    ]

    /// Приводит строку чека к виду, по которому можно сравнивать: без регистра,
    /// без диакритики, без цифр и знаков.
    static func normalize(_ text: String) -> String {
        let folded = text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "es_ES"))
        var result = ""
        for character in folded {
            if character.isLetter || character == " " {
                result.append(character)
            } else {
                result.append(" ")
            }
        }
        let parts = result.split(separator: " ").map(String.init)
        return parts.joined(separator: " ")
    }

    /// Ищет товар справочника: сначала среди запомненных исправлений, потом по ключевым словам.
    static func match(_ text: String, aliases: [String: String]) -> BasketProduct? {
        let normalized = normalize(text)
        guard !normalized.isEmpty else { return nil }

        if let productID = aliases[normalized], let product = BasketCatalog.product(id: productID) {
            return product
        }

        // Побеждает самое длинное совпавшее слово: «leche infantil» важнее, чем «leche».
        var bestID: String? = nil
        var bestLength = 0
        for (productID, words) in keywords {
            for word in words {
                let needle = normalize(word)
                guard !needle.isEmpty, needle.count > bestLength else { continue }
                if normalized.contains(needle) {
                    bestLength = needle.count
                    bestID = productID
                }
            }
        }

        guard let bestID = bestID else { return nil }
        return BasketCatalog.product(id: bestID)
    }

    /// Категория для строки чека: по найденному товару, иначе бакалея как нейтральный вариант.
    static func category(for text: String, aliases: [String: String]) -> BasketCategory {
        match(text, aliases: aliases)?.category ?? .grocery
    }

    /// Ключ, под которым запоминается ручное исправление пользователя.
    static func aliasKey(for text: String) -> String {
        normalize(text)
    }
}
