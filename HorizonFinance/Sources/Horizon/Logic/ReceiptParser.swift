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
        receipt.merchantName = detectMerchantName(in: document.lines) ?? receipt.merchantName
        receipt.chainID = detectChainID(name: receipt.merchantName, lines: document.lines)
        if receipt.date == nil { receipt.date = detectDate(in: document.lines) }
        receipt.printedTotal = detectTotal(in: document.lines)
        receipt.lines = detectItems(in: document.lines, aliases: aliases)

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

    static func detectMerchantName(in lines: [String]) -> String? {
        let head = lines.prefix(8)
        for line in head {
            let normalized = ProductMatcher.normalize(line)
            for country in BasketCatalog.countries {
                for chain in country.chains {
                    let needle = ProductMatcher.normalize(chain.name)
                    if containsWord(normalized, needle) {
                        return chain.name
                    }
                }
            }
        }
        // Иначе берём первую содержательную строку — обычно это вывеска магазина.
        for line in head {
            let cleaned = line.trimmingCharacters(in: .whitespaces)
            if cleaned.count >= 3 && ProductMatcher.normalize(cleaned).count >= 3 && !isServiceLine(cleaned) {
                return cleaned
            }
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

    static func detectChainID(name: String, lines: [String]) -> String? {
        let haystack = ProductMatcher.normalize(name + " " + lines.prefix(8).joined(separator: " "))
        guard !haystack.isEmpty else { return nil }
        for country in BasketCatalog.countries {
            for chain in country.chains {
                if containsWord(haystack, ProductMatcher.normalize(chain.name)) { return chain.id }
            }
        }
        return nil
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

    private static let totalKeywords = ["total a pagar", "total", "importe total", "a pagar", "importe", "guztira"]
    private static let totalExclusions = ["articulos", "iva", "base", "descuento", "ahorro", "puntos", "acumulado"]

    static func detectTotal(in lines: [String]) -> Double? {
        var candidate: Double? = nil
        for line in lines {
            let normalized = ProductMatcher.normalize(line)
            guard totalKeywords.contains(where: { normalized.contains($0) }) else { continue }
            guard !totalExclusions.contains(where: { normalized.contains($0) }) else { continue }
            if let value = money(in: line).last, value > 0 {
                candidate = value
            }
        }
        return candidate
    }

    // MARK: Позиции

    private static let stopWords = [
        "iva", "base imponible", "cuota", "tarjeta", "efectivo", "cambio", "entregado",
        "total", "importe", "a pagar", "gracias", "atendido", "caja", "cajero", "operacion",
        "factura", "ticket", "tbai", "verifactu", "nif", "cif", "telefono", "direccion",
        "socio", "puntos", "ahorro", "descuentos", "articulos", "www", "horario", "devolucion",
        "cliente", "vendedor", "fecha", "hora", "copia", "original", "iban", "autorizacion"
    ]

    static func isServiceLine(_ line: String) -> Bool {
        let normalized = ProductMatcher.normalize(line)
        guard !normalized.isEmpty else { return true }
        return stopWords.contains(where: { normalized.contains($0) })
    }

    static func detectItems(in lines: [String], aliases: [String: String]) -> [ReceiptLine] {
        var items: [ReceiptLine] = []

        for raw in lines {
            let trimmed = raw.trimmingCharacters(in: .whitespaces)
            guard trimmed.count >= 4, !isServiceLine(trimmed) else { continue }

            let values = money(in: trimmed)
            guard let amountValue = values.last else { continue }

            let namePart = nameFragment(of: trimmed)
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

    static func isDiscountLine(_ line: String) -> Bool {
        let normalized = ProductMatcher.normalize(line)
        if normalized.contains("dto") || normalized.contains("descuento") || normalized.contains("promocion") {
            return true
        }
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

    /// Количество: явное «2 x», вес «0,462 kg» или единица по умолчанию.
    static func quantity(in line: String) -> Double {
        if let groups = firstMatch(pattern: "([0-9]+[.,][0-9]+)\\s*(kg|kilo|l|lt)", in: line.lowercased()),
           groups.count >= 2,
           let weight = parseMoney(groups[1]), weight > 0 {
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
