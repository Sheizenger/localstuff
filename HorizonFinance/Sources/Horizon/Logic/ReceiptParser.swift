import Foundation

/// Превращает распознанный текст чека в позиции, дату, магазин и итог.
///
/// Разбор намеренно консервативный: лучше не узнать строку и показать её пользователю,
/// чем тихо записать в расходы выдумку. Итог всегда сверяется с суммой позиций.
enum ReceiptParser {

    // MARK: Разбор

    static func parse(_ document: ScannedDocument, aliases: [String: String]) -> ParsedReceipt {
        var receipt = ParsedReceipt()
        receipt.rawText = document.lines

        applyCodes(document.codes, to: &receipt)
        let chain = detectChain(in: document.lines)
        receipt.chainID = chain?.id
        receipt.merchantName = chain?.name ?? detectMerchantName(in: document.lines) ?? receipt.merchantName
        if receipt.date == nil { receipt.date = detectDate(in: document.lines) }
        receipt.printedTotal = detectTotal(in: document.lines)
        receipt.lines = detectItems(in: document.lines, aliases: aliases)
        reconcile(&receipt)

        if receipt.lines.isEmpty {
            receipt.warnings.append("Не удалось разобрать ни одной позиции — проверьте качество снимка.")
        }
        if receipt.printedTotal == nil {
            receipt.warnings.append("В чеке не нашёлся итог, сумма посчитана по позициям.")
        } else if let mismatch = receipt.mismatch, abs(mismatch) >= 0.05 {
            let sign = mismatch > 0 ? "не хватает" : "лишние"
            receipt.warnings.append("Позиции не сходятся с итогом: \(sign) \(String(format: "%.2f", abs(mismatch))). Поправьте строки перед записью.")
        }
        if document.usedOCR && document.codes.isEmpty {
            receipt.warnings.append("QR-кода на снимке не видно — дату и магазин стоит проверить.")
        }

        return receipt
    }

    // MARK: QR и коды

    /// Испанские чеки несут QR TicketBAI (Страна Басков) или Verifactu.
    /// Позиций там нет, но есть налоговый номер продавца и дата — это надёжнее OCR.
    static func applyCodes(_ codes: [String], to receipt: inout ParsedReceipt) {
        for code in codes {
            if let groups = firstMatch(pattern: "TBAI-([A-Z0-9]+)-([0-9]{6})-", in: code.uppercased()), groups.count >= 3 {
                receipt.receiptCode = "TBAI-\(groups[1])-\(groups[2])"
                receipt.sellerTaxID = groups[1]
                if let date = dateFromDDMMYY(groups[2]) { receipt.date = date }
                continue
            }
            if let groups = firstMatch(pattern: "NIF=([A-Z0-9]+)", in: code.uppercased()), groups.count >= 2 {
                receipt.sellerTaxID = groups[1]
                receipt.receiptCode = receipt.receiptCode ?? code
            }
        }
    }

    // MARK: Магазин

    /// Сравнение по целым словам: иначе «Dia» находится внутри «MEDIA» и «DIARIO».
    static func containsWord(_ haystack: String, _ needle: String) -> Bool {
        guard !needle.isEmpty, !haystack.isEmpty else { return false }
        return (" " + haystack + " ").contains(" " + needle + " ")
    }

    /// Запасной вариант, когда сети нет в справочнике: первая содержательная строка шапки.
    /// Строку с ценой пропускаем — это уже позиция, а не вывеска.
    static func detectMerchantName(in lines: [String]) -> String? {
        for line in lines.prefix(8) {
            let cleaned = line.trimmingCharacters(in: .whitespaces)
            guard cleaned.count >= 3, ProductMatcher.normalize(cleaned).count >= 3 else { continue }
            guard !isServiceLine(cleaned), money(in: cleaned).isEmpty else { continue }
            return cleaned
        }
        return nil
    }

    /// Заведения, чей чек логичнее записать в фаст-фуд, а не в продукты.
    static let fastFoodMerchants = [
        "mcdonald", "burger king", "kfc", "telepizza", "domino", "goiko", "subway",
        "papa john", "five guys", "taco bell", "pans", "rodilla", "vips", "starbucks",
        "glovo", "uber eats", "just eat", "deliveroo", "kebab", "pizzeria"
    ]

    static func isFastFood(_ merchant: String) -> Bool {
        let normalized = ProductMatcher.normalize(merchant)
        guard !normalized.isEmpty else { return false }
        return fastFoodMerchants.contains { normalized.contains(ProductMatcher.normalize($0)) }
    }

    /// Сеть ищем сначала в шапке, а если там не нашлось — по всему чеку.
    ///
    /// У BM вывеска в шапке сокращена до «BM», а полное «BM SUPERMERCADOS» стоит
    /// в подвале, после позиций. По всему чеку ищем только длинные названия: короткое
    /// «Dia» или «Coop» слишком легко встретить внутри обычного текста.
    static func detectChain(in lines: [String]) -> StoreChain? {
        if let fromHeader = firstChain(inText: lines.prefix(10).joined(separator: " "), minimumLength: 1) {
            return fromHeader
        }
        return firstChain(inText: lines.joined(separator: " "), minimumLength: 5)
    }

    static func firstChain(inText text: String, minimumLength: Int) -> StoreChain? {
        let haystack = ProductMatcher.normalize(text)
        guard !haystack.isEmpty else { return nil }

        // Побеждает самое длинное название: «BM Supermercados» точнее, чем «BM».
        var best: StoreChain? = nil
        var bestLength = 0
        for country in BasketCatalog.countries {
            for chain in country.chains {
                let needle = ProductMatcher.normalize(chain.name)
                guard needle.count >= minimumLength, needle.count > bestLength else { continue }
                if containsWord(haystack, needle) {
                    best = chain
                    bestLength = needle.count
                }
            }
        }
        return best
    }

    // MARK: Дата

    static func detectDate(in lines: [String]) -> Date? {
        for line in lines {
            guard let groups = firstMatch(pattern: "([0-9]{1,2})[./-]([0-9]{1,2})[./-]([0-9]{2,4})", in: line),
                  groups.count >= 4,
                  let day = Int(groups[1]), let month = Int(groups[2]), var year = Int(groups[3])
            else { continue }

            if year < 100 { year += 2000 }
            guard (1...31).contains(day), (1...12).contains(month), (2000...2100).contains(year) else { continue }

            var parts = DateComponents()
            parts.year = year
            parts.month = month
            parts.day = day
            parts.hour = 12
            if let date = Cal.ru.date(from: parts) { return date }
        }
        return nil
    }

    static func dateFromDDMMYY(_ text: String) -> Date? {
        guard text.count == 6 else { return nil }
        let chars = Array(text)
        guard let day = Int(String(chars[0...1])),
              let month = Int(String(chars[2...3])),
              let year = Int(String(chars[4...5]))
        else { return nil }
        var parts = DateComponents()
        parts.year = 2000 + year
        parts.month = month
        parts.day = day
        parts.hour = 12
        return Cal.ru.date(from: parts)
    }

    // MARK: Итог

    private static let totalKeywords = ["total", "importe total", "a pagar", "importe", "guztira"]
    private static let totalExclusions = ["articulos", "base", "cuota", "descuento", "ahorro", "puntos", "acumulado"]

    /// Итог ищем только в строках, которые с него и начинаются.
    ///
    /// «TOTAL COMPRA (iva incl.)» — это итог, а «Tipo Base Iva Req Total» — шапка
    /// налоговой таблицы: слово «total» там в конце. Из подходящих берём наибольшую
    /// сумму: в чеке рядом стоят «total artículos» и настоящий итог к оплате.
    static func detectTotal(in lines: [String]) -> Double? {
        var candidate: Double? = nil
        for line in lines {
            let normalized = ProductMatcher.normalize(line)
            guard totalKeywords.contains(where: { normalized.hasPrefix($0) }) else { continue }
            guard !totalExclusions.contains(where: { normalized.contains($0) }) else { continue }
            guard let value = money(in: line).last, value > 0 else { continue }
            candidate = max(candidate ?? 0, value)
        }
        return candidate
    }

    // MARK: Сверка с итогом

    /// Приводит позиции к напечатанному итогу, когда расходится только строка скидки.
    ///
    /// BM печатает «Promoción DTO 20%: 0.42 €» справочно — цены позиций уже со скидкой,
    /// и вычесть её ещё раз значит занизить чек. Другие сети, наоборот, печатают скидку
    /// отдельной строкой, которую вычитать нужно. Кто из них прав в этом чеке, решает итог.
    static func reconcile(_ receipt: inout ParsedReceipt) {
        guard let printed = receipt.printedTotal, printed > 0 else { return }
        guard abs(printed - receipt.linesTotal) > 0.02 else { return }
        guard receipt.lines.contains(where: { $0.isDiscount }) else { return }

        let withoutDiscounts = receipt.lines.filter { !$0.isDiscount }
        if abs(printed - withoutDiscounts.reduce(0.0) { $0 + $1.amount }) <= 0.02 {
            receipt.lines = withoutDiscounts
            receipt.warnings.append("Скидка в чеке указана справочно — цены позиций уже с ней. Строка скидки убрана, чтобы не вычесть её дважды.")
            return
        }

        let flipped = receipt.lines.map { line -> ReceiptLine in
            guard line.isDiscount else { return line }
            var copy = line
            copy.amount = abs(line.amount)
            copy.isDiscount = false
            return copy
        }
        if abs(printed - flipped.reduce(0.0) { $0 + $1.amount }) <= 0.02 {
            receipt.lines = flipped
            receipt.warnings.append("Строка со словом «скидка» оказалась обычной позицией — так сходится с итогом чека.")
        }
    }

    // MARK: Позиции

    private static let stopWords = [
        "base imponible", "cuota", "tarjeta", "efectivo", "cambio", "entregado",
        "total", "importe", "a pagar", "gracias", "atendido", "caja", "cajero", "operacion",
        "factura", "ticket", "tbai", "verifactu", "nif", "cif", "telefono", "direccion",
        "socio", "puntos", "ahorro", "descuentos", "articulos", "www", "horario", "devolucion",
        "cliente", "vendedor", "fecha", "hora", "copia", "original", "iban", "autorizacion",
        // Подвал чека: благодарности и «сколько бы вы сэкономили с картой».
        "ahorrado", "hubieras", "eskerrik", "atencion al cliente", "por comprar", "tipo base",
        // Заголовки отделов — не товар.
        "fruteria", "alimentacion", "drogueria", "perfumeria", "carniceria", "pescaderia",
        "panaderia", "charcuteria"
    ]

    /// Слова, которые ловим только целиком: «iva» иначе найдётся внутри «AVIVA» и «IVAN».
    private static let stopWordsExact = ["iva"]

    static func isServiceLine(_ line: String) -> Bool {
        let normalized = ProductMatcher.normalize(line)
        guard !normalized.isEmpty else { return true }
        // Строка скидки выглядит служебной, но её нужно разобрать — она меняет сумму чека.
        if discountPrefixes.contains(where: { normalized.hasPrefix($0) }) { return false }
        if stopWords.contains(where: { normalized.contains($0) }) { return true }
        return stopWordsExact.contains(where: { containsWord(normalized, $0) })
    }

    static func lettersOnly(_ text: String) -> String {
        ProductMatcher.normalize(text).replacingOccurrences(of: " ", with: "")
    }

    static func detectItems(in lines: [String], aliases: [String: String]) -> [ReceiptLine] {
        var items: [ReceiptLine] = []
        /// Название с предыдущей строки: Mercadona печатает весовой товар в две строки —
        /// «PLATANO», а под ним «0,462 kg x 2,15 EUR/kg   0,99».
        var carriedName: String? = nil

        for raw in lines {
            let trimmed = raw.trimmingCharacters(in: .whitespaces)
            guard trimmed.count >= 4, !isServiceLine(trimmed) else {
                carriedName = nil
                continue
            }

            let values = money(in: trimmed)
            guard let amountValue = values.last else {
                // Строка без суммы, но со словами — возможно, название весового товара.
                let candidate = nameFragment(of: trimmed)
                carriedName = lettersOnly(candidate).count >= 3 ? candidate : nil
                continue
            }

            var namePart = nameFragment(of: trimmed)
            if lettersOnly(namePart).count < 3, let carried = carriedName {
                namePart = carried
            }
            carriedName = nil

            let letters = ProductMatcher.normalize(namePart)
            guard letters.replacingOccurrences(of: " ", with: "").count >= 3 else { continue }

            let discount = isDiscountLine(trimmed)
            let signedAmount = discount ? -abs(amountValue) : abs(amountValue)
            guard abs(signedAmount) > 0.0001 else { continue }

            var line = ReceiptLine()
            line.raw = trimmed
            line.name = namePart
            line.quantity = quantity(in: trimmed)
            line.amount = signedAmount
            line.isDiscount = discount

            if let product = ProductMatcher.match(namePart, aliases: aliases) {
                line.productID = product.id
                line.category = product.category
            } else {
                line.category = .grocery
            }

            items.append(line)
        }

        return items
    }

    /// Скидка — это строка, которая со слова о скидке начинается.
    ///
    /// Раньше хватало слова «dto» в любом месте, и товар «RUCULA 20% DTO» уходил
    /// в минус: акция в названии — это всё ещё покупка.
    static let discountPrefixes = ["dto", "descuento", "promocion", "promo", "ahorro", "cupon", "vale"]

    static func isDiscountLine(_ line: String) -> Bool {
        let normalized = ProductMatcher.normalize(line)
        if discountPrefixes.contains(where: { normalized.hasPrefix($0) }) { return true }
        // Явный минус перед суммой в конце строки.
        return firstMatch(pattern: "-\\s?[0-9]+[.,][0-9]{2}\\s*€?\\s*$", in: line) != nil
    }

    /// Название — это то, что осталось после чисел в начале и суммы в конце.
    static func nameFragment(of line: String) -> String {
        var text = line
        if let range = text.range(of: "^\\s*[0-9]+([.,][0-9]+)?\\s*(x|X)?\\s+", options: .regularExpression) {
            text = String(text[range.upperBound...])
        }
        // Весовые позиции печатают как «0,462 kg x 7,60 EUR/kg НАЗВАНИЕ» — цену за килограмм тоже убираем.
        if let range = text.range(
            of: "^\\s*(kg|l|lt|ud|uds|kilo)?\\s*(x)?\\s*[0-9]+[.,][0-9]+\\s*(eur|€)?\\s*/?\\s*(kg|l|ud)?\\s*",
            options: [.regularExpression, .caseInsensitive]
        ) {
            text = String(text[range.upperBound...])
        }
        if let range = text.range(of: "\\s+[-0-9.,€\\s]+$", options: .regularExpression) {
            text = String(text[..<range.lowerBound])
        }
        return text.trimmingCharacters(in: CharacterSet(charactersIn: " \t.,;:*-")).trimmingCharacters(in: .whitespaces)
    }

    /// Количество: вес или дробное число в начале строки, явное «2 x», иначе единица.
    ///
    /// Число ищем именно в начале: в колонке количества. Внутри названия цифры значат
    /// объём упаковки — «LIMONADA D.SIMON 1,5L» это одна бутылка, а не полтора литра на вес.
    static func quantity(in line: String) -> Double {
        if let groups = firstMatch(pattern: "^\\s*([0-9]+[.,][0-9]+)\\s*(kg|kilo|l|lt|ud|uds)?\\s", in: line.lowercased()),
           groups.count >= 2,
           let weight = parseMoney(groups[1]), weight > 0, weight < 100 {
            return weight
        }
        if let groups = firstMatch(pattern: "^\\s*([0-9]{1,2})\\s+", in: line), groups.count >= 2,
           let count = Double(groups[1]), count >= 1, count <= 30 {
            return count
        }
        if let groups = firstMatch(pattern: "([0-9]{1,2})\\s?(x|X)\\s?[0-9]", in: line), groups.count >= 2,
           let count = Double(groups[1]), count >= 1, count <= 30 {
            return count
        }
        return 1
    }

    // MARK: Мелкие помощники

    static func money(in text: String) -> [Double] {
        var result: [Double] = []
        guard let expression = try? NSRegularExpression(pattern: "[0-9]{1,5}[.,][0-9]{2}(?![0-9])") else { return [] }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        for match in expression.matches(in: text, range: range) {
            guard let matchRange = Range(match.range, in: text) else { continue }
            if let value = parseMoney(String(text[matchRange])) { result.append(value) }
        }
        return result
    }

    static func parseMoney(_ text: String) -> Double? {
        let cleaned = text
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "€", with: "")
            .replacingOccurrences(of: ",", with: ".")
        return Double(cleaned)
    }

    /// Возвращает всю совпавшую строку и группы, как в привычных регулярках.
    static func firstMatch(pattern: String, in text: String) -> [String]? {
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        guard let match = expression.firstMatch(in: text, range: range) else { return nil }

        var groups: [String] = []
        for index in 0..<match.numberOfRanges {
            if let groupRange = Range(match.range(at: index), in: text) {
                groups.append(String(text[groupRange]))
            } else {
                groups.append("")
            }
        }
        return groups
    }
}
