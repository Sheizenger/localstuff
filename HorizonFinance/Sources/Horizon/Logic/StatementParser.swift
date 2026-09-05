import Foundation

/// Одна строка банковской выписки после разбора.
struct StatementRow: Identifiable, Hashable {
    var id: UUID = UUID()
    var date: Date
    var details: String
    /// Со знаком: минус — расход, плюс — поступление.
    var amount: Double
    var raw: String = ""
    var categoryID: UUID? = nil
    /// Похоже, такая операция уже есть в приложении.
    var isDuplicate: Bool = false
    var include: Bool = true

    var flow: MoneyFlow { amount >= 0 ? .income : .expense }
}

struct ParsedStatement {
    var rows: [StatementRow] = []
    var warnings: [String] = []
    /// Что удалось понять про колонки — показывается пользователю для проверки.
    var columnsNote: String = ""
    var skipped: Int = 0

    var total: Double { rows.filter { $0.include }.reduce(0.0) { $0 + $1.amount } }
    var incomeTotal: Double { rows.filter { $0.include && $0.amount > 0 }.reduce(0.0) { $0 + $1.amount } }
    var expenseTotal: Double { rows.filter { $0.include && $0.amount < 0 }.reduce(0.0) { $0 + abs($1.amount) } }
}

/// Разбор выписки в CSV: банки отдают её по-разному, поэтому колонки и формат чисел
/// определяются по содержимому, а не по жёсткой схеме.
enum StatementParser {

    enum ParseError: LocalizedError {
        case unreadable
        case noRows

        var errorDescription: String? {
            switch self {
            case .unreadable: return "Файл не читается. Нужен CSV или TXT из банка."
            case .noRows: return "В файле не нашлось ни одной операции с датой и суммой."
            }
        }
    }

    // MARK: Чтение файла

    static func loadText(url: URL) throws -> String {
        guard let data = try? Data(contentsOf: url) else { throw ParseError.unreadable }
        let encodings: [String.Encoding] = [.utf8, .windowsCP1252, .isoLatin1, .utf16]
        for encoding in encodings {
            if let text = String(data: data, encoding: encoding), !text.isEmpty {
                return text
            }
        }
        throw ParseError.unreadable
    }

    // MARK: Разбор

    static func detectDelimiter(in lines: [String]) -> Character {
        let candidates: [Character] = [";", ",", "\t", "|"]
        var best: Character = ";"
        var bestCount = 0
        for candidate in candidates {
            let count = lines.prefix(10).reduce(0) { $0 + $1.filter { $0 == candidate }.count }
            if count > bestCount {
                bestCount = count
                best = candidate
            }
        }
        return best
    }

    /// Разбивает строку CSV с учётом кавычек.
    static func splitLine(_ line: String, delimiter: Character) -> [String] {
        var cells: [String] = []
        var current = ""
        var inQuotes = false
        var iterator = line.makeIterator()

        while let character = iterator.next() {
            if character == "\"" {
                inQuotes.toggle()
                continue
            }
            if character == delimiter && !inQuotes {
                cells.append(current.trimmingCharacters(in: .whitespaces))
                current = ""
                continue
            }
            current.append(character)
        }
        cells.append(current.trimmingCharacters(in: .whitespaces))
        return cells
    }

    static func parseDate(_ text: String) -> Date? {
        let cleaned = text.trimmingCharacters(in: .whitespaces)
        guard cleaned.count >= 6 else { return nil }

        // dd/MM/yyyy, dd-MM-yy, dd.MM.yyyy
        if let groups = ReceiptParser.firstMatch(pattern: "^([0-9]{1,2})[./-]([0-9]{1,2})[./-]([0-9]{2,4})", in: cleaned),
           groups.count >= 4,
           let day = Int(groups[1]), let month = Int(groups[2]), var year = Int(groups[3]) {
            if year < 100 { year += 2000 }
            if (1...31).contains(day) && (1...12).contains(month) && (2000...2100).contains(year) {
                return RecurrenceEngine.makeDate(year: year, month: month, day: day)
            }
        }

        // yyyy-MM-dd
        if let groups = ReceiptParser.firstMatch(pattern: "^([0-9]{4})[./-]([0-9]{1,2})[./-]([0-9]{1,2})", in: cleaned),
           groups.count >= 4,
           let year = Int(groups[1]), let month = Int(groups[2]), let day = Int(groups[3]) {
            if (1...31).contains(day) && (1...12).contains(month) && (2000...2100).contains(year) {
                return RecurrenceEngine.makeDate(year: year, month: month, day: day)
            }
        }

        return nil
    }

    /// Понимает и «1.234,56», и «1,234.56», и «-45,20 €».
    static func parseAmount(_ text: String) -> Double? {
        // Дата вроде «2026-09-03» без этой проверки превращается в число 20260903.
        if parseDate(text) != nil { return nil }

        var cleaned = text
            .replacingOccurrences(of: "€", with: "")
            .replacingOccurrences(of: "EUR", with: "")
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "\u{00A0}", with: "")
            .trimmingCharacters(in: .whitespaces)
        guard !cleaned.isEmpty else { return nil }

        var isNegative = cleaned.hasPrefix("-")
        if cleaned.hasPrefix("(") && cleaned.hasSuffix(")") {
            isNegative = true
            cleaned = String(cleaned.dropFirst().dropLast())
        }
        cleaned = cleaned.replacingOccurrences(of: "+", with: "")
        cleaned = cleaned.replacingOccurrences(of: "-", with: "")

        let hasComma = cleaned.contains(",")
        let hasDot = cleaned.contains(".")

        if hasComma && hasDot {
            // Разделитель дробной части — тот знак, который правее.
            if cleaned.distance(from: cleaned.startIndex, to: cleaned.lastIndex(of: ",") ?? cleaned.startIndex)
                > cleaned.distance(from: cleaned.startIndex, to: cleaned.lastIndex(of: ".") ?? cleaned.startIndex) {
                cleaned = cleaned.replacingOccurrences(of: ".", with: "")
                cleaned = cleaned.replacingOccurrences(of: ",", with: ".")
            } else {
                cleaned = cleaned.replacingOccurrences(of: ",", with: "")
            }
        } else if hasComma {
            cleaned = cleaned.replacingOccurrences(of: ",", with: ".")
        }

        guard let value = Double(cleaned), value.isFinite else { return nil }
        return isNegative ? -value : value
    }

    private static let dateHeaders = ["fecha", "date", "data", "f. valor", "f.valor", "fecha operacion", "дата"]
    private static let detailHeaders = ["concepto", "descripcion", "description", "detalle", "movimiento",
                                        "beneficiario", "referencia", "observaciones", "описание", "назначение"]
    private static let amountHeaders = ["importe", "amount", "cantidad", "valor", "сумма"]
    private static let balanceHeaders = ["saldo", "balance", "остаток"]

    private static func headerIndex(_ cells: [String], among keys: [String]) -> Int? {
        for (index, cell) in cells.enumerated() {
            let normalized = ProductMatcher.normalize(cell)
            guard !normalized.isEmpty else { continue }
            if keys.contains(where: { normalized.contains(ProductMatcher.normalize($0)) }) {
                return index
            }
        }
        return nil
    }

    static func parse(text: String) -> ParsedStatement {
        var statement = ParsedStatement()

        let allLines = text
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        guard !allLines.isEmpty else {
            statement.warnings.append("Файл пустой.")
            return statement
        }

        let delimiter = detectDelimiter(in: allLines)
        let table = allLines.map { splitLine($0, delimiter: delimiter) }

        // Ищем строку заголовка среди первых десяти.
        var headerRow: Int? = nil
        var dateColumn: Int? = nil
        var detailColumn: Int? = nil
        var amountColumn: Int? = nil

        for (index, cells) in table.prefix(10).enumerated() {
            guard cells.count >= 2 else { continue }
            let date = headerIndex(cells, among: dateHeaders)
            let amount = headerIndex(cells, among: amountHeaders)
            if date != nil && amount != nil {
                headerRow = index
                dateColumn = date
                amountColumn = amount
                detailColumn = headerIndex(cells, among: detailHeaders)
                break
            }
        }

        let dataRows = headerRow.map { Array(table.dropFirst($0 + 1)) } ?? table

        if dateColumn == nil || amountColumn == nil {
            let guess = inferColumns(in: dataRows)
            dateColumn = guess.date
            amountColumn = guess.amount
            detailColumn = guess.detail
            statement.columnsNote = "Заголовок не найден, колонки определены по содержимому."
        } else {
            statement.columnsNote = "Колонки взяты из заголовка файла."
        }

        guard let dateIndex = dateColumn, let amountIndex = amountColumn else {
            statement.warnings.append("Не удалось понять, где дата и где сумма.")
            return statement
        }

        for cells in dataRows {
            guard cells.count > max(dateIndex, amountIndex) else {
                statement.skipped += 1
                continue
            }
            guard let date = parseDate(cells[dateIndex]),
                  let amount = parseAmount(cells[amountIndex]),
                  abs(amount) > 0.0001
            else {
                statement.skipped += 1
                continue
            }

            var details = ""
            if let detailIndex = detailColumn, cells.count > detailIndex {
                details = cells[detailIndex]
            }
            if details.isEmpty {
                // Берём самую длинную текстовую ячейку — обычно это назначение платежа.
                details = cells.enumerated()
                    .filter { $0.offset != dateIndex && $0.offset != amountIndex }
                    .map { $0.element }
                    .filter { parseAmount($0) == nil }
                    .max(by: { $0.count < $1.count }) ?? "Операция"
            }

            statement.rows.append(
                StatementRow(
                    date: date,
                    details: details.isEmpty ? "Операция" : details,
                    amount: amount,
                    raw: cells.joined(separator: " | ")
                )
            )
        }

        if statement.rows.isEmpty {
            statement.warnings.append("Строк с датой и суммой не нашлось — проверьте, что это выписка, а не отчёт.")
        }
        if statement.skipped > 0 {
            statement.warnings.append("Пропущено строк без даты или суммы: \(statement.skipped). Обычно это шапка и итоги.")
        }
        return statement
    }

    /// Когда заголовка нет: ищем колонку с датами и колонку с суммами по самим значениям.
    static func inferColumns(in rows: [[String]]) -> (date: Int?, amount: Int?, detail: Int?) {
        let sample = Array(rows.prefix(40))
        guard let width = sample.map({ $0.count }).max(), width > 0 else { return (nil, nil, nil) }

        var dateHits = [Int](repeating: 0, count: width)
        var moneyHits = [Int](repeating: 0, count: width)
        var negativeHits = [Int](repeating: 0, count: width)
        var textLength = [Int](repeating: 0, count: width)

        for cells in sample {
            for (index, cell) in cells.enumerated() where index < width {
                if parseDate(cell) != nil { dateHits[index] += 1 }
                if let value = parseAmount(cell) {
                    moneyHits[index] += 1
                    if value < 0 { negativeHits[index] += 1 }
                } else {
                    textLength[index] += cell.count
                }
            }
        }

        let dateIndex = dateHits.enumerated().max(by: { $0.element < $1.element })
            .flatMap { $0.element > 0 ? $0.offset : nil }

        // Сумма — это колонка со знаками, а не остаток по счёту: остаток редко бывает отрицательным.
        var amountIndex: Int? = nil
        var bestScore = -1
        for index in 0..<width where moneyHits[index] > 0 && index != dateIndex {
            let score = moneyHits[index] + negativeHits[index] * 3
            if score > bestScore {
                bestScore = score
                amountIndex = index
            }
        }

        // Описание ищем среди оставшихся колонок: дата тоже «не число», но описанием не является.
        var detailIndex: Int? = nil
        var bestText = 0
        for index in 0..<width where index != dateIndex && index != amountIndex {
            if textLength[index] > bestText {
                bestText = textLength[index]
                detailIndex = index
            }
        }

        return (dateIndex, amountIndex, detailIndex)
    }
}
