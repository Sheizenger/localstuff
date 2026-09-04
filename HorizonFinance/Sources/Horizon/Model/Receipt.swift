import Foundation

/// Одна позиция чека после разбора.
struct ReceiptLine: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    /// Как строка выглядела в чеке — чтобы всегда можно было проверить разбор.
    var raw: String = ""
    var name: String = ""
    var quantity: Double = 1
    /// Сумма по строке. У скидок отрицательная.
    var amount: Double = 0
    /// Товар из справочника корзины, если удалось узнать.
    var productID: String? = nil
    var category: BasketCategory = .grocery
    var isDiscount: Bool = false

    var unitPrice: Double {
        guard quantity > 0.0001 else { return amount }
        return amount / quantity
    }

    enum CodingKeys: String, CodingKey {
        case id, raw, name, quantity, amount, productID, category, isDiscount
    }
}

extension ReceiptLine {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var line = ReceiptLine()
        line.id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        line.raw = try container.decodeIfPresent(String.self, forKey: .raw) ?? ""
        line.name = try container.decodeIfPresent(String.self, forKey: .name) ?? ""
        line.quantity = try container.decodeIfPresent(Double.self, forKey: .quantity) ?? 1
        line.amount = try container.decodeIfPresent(Double.self, forKey: .amount) ?? 0
        line.productID = try container.decodeIfPresent(String.self, forKey: .productID)
        line.category = try container.decodeIfPresent(BasketCategory.self, forKey: .category) ?? .grocery
        line.isDiscount = try container.decodeIfPresent(Bool.self, forKey: .isDiscount) ?? false
        self = line
    }
}

/// Результат разбора чека до того, как он записан в операции.
struct ParsedReceipt {
    var merchantName: String = ""
    /// Идентификатор сети из справочника, если магазин удалось узнать.
    var chainID: String? = nil
    var date: Date? = nil
    /// Итог, напечатанный в чеке. Именно он сверяется с суммой позиций.
    var printedTotal: Double? = nil
    var lines: [ReceiptLine] = []
    /// Идентификатор TicketBAI или другой код из QR — доказательство, что чек настоящий.
    var receiptCode: String? = nil
    var sellerTaxID: String? = nil
    /// Текст, который увидел распознаватель — на случай, если разбор ошибся.
    var rawText: [String] = []
    var warnings: [String] = []

    var linesTotal: Double {
        lines.reduce(0.0) { $0 + $1.amount }
    }

    /// Расхождение между напечатанным итогом и суммой позиций.
    var mismatch: Double? {
        guard let printed = printedTotal else { return nil }
        return printed - linesTotal
    }

    var isConsistent: Bool {
        guard let mismatch = mismatch else { return false }
        return abs(mismatch) < 0.05
    }

    /// Сумма, которую разумно записать в операцию.
    var amountToRecord: Double {
        if let printed = printedTotal, printed > 0 { return printed }
        return max(linesTotal, 0)
    }

    func total(of category: BasketCategory) -> Double {
        lines.filter { $0.category == category }.reduce(0.0) { $0 + $1.amount }
    }

    /// То, что в приложении считается свободными тратами: бытовое и алкоголь.
    var flexiblePart: Double {
        lines
            .filter { $0.category == .household || $0.productID == "alcohol" }
            .reduce(0.0) { $0 + $1.amount }
    }
}
