import SwiftUI

/// Одна строка чека в редактируемом виде.
///
/// Используется и при разборе снимка, и при правке уже записанного чека —
/// чтобы поля вели себя одинаково в обоих местах.
struct ReceiptLineRow: View {
    @EnvironmentObject private var store: Store

    @Binding var line: ReceiptLine
    var onDelete: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                TextField("Название", text: $line.name)
                    .textFieldStyle(.plain)
                    .font(.body)
                if !line.raw.isEmpty {
                    Text(line.raw)
                        .font(.caption2)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                        .help(line.raw)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Picker("", selection: productBinding) {
                Text("не узнан").tag("")
                ForEach(BasketCatalog.products) { product in
                    Text("\(product.category.emoji) \(product.name)").tag(product.id)
                }
            }
            .labelsHidden()
            .frame(width: 190)

            TextField("", value: $line.quantity, format: .number.precision(.fractionLength(0...3)))
                .textFieldStyle(.roundedBorder)
                .multilineTextAlignment(.trailing)
                .frame(width: 60)
                .help("Количество или вес")

            TextField("", value: $line.amount, format: .number.precision(.fractionLength(2)))
                .textFieldStyle(.roundedBorder)
                .multilineTextAlignment(.trailing)
                .frame(width: 76)
                .help("Сумма по строке. Скидка — со знаком минус.")

            Button(action: onDelete) {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help("Убрать строку")
        }
        .padding(.vertical, 2)
    }

    /// Выбор товара из справочника: заодно чинит категорию и учит разбор на будущее.
    private var productBinding: Binding<String> {
        Binding(
            get: { line.productID ?? "" },
            set: { newValue in
                if newValue.isEmpty {
                    line.productID = nil
                    return
                }
                guard let product = BasketCatalog.product(id: newValue) else { return }
                line.productID = product.id
                line.category = product.category
                store.rememberAlias(text: line.name, productID: product.id)
            }
        )
    }
}

/// Правка уже прикреплённого чека: позиции и итоговая сумма операции.
///
/// Распознавание ошибается — то склеит две строки, то не увидит скидку. Здесь всё
/// это чинится руками, а сумма операции и сумма позиций всегда на виду рядом,
/// чтобы расхождение нельзя было не заметить.
struct ReceiptEditor: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    var merchant: String
    @Binding var lines: [ReceiptLine]
    @Binding var amount: Double

    @State private var draftLines: [ReceiptLine] = []
    @State private var draftAmount: Double = 0
    @State private var loaded = false

    private var linesTotal: Double {
        draftLines.reduce(0.0) { $0 + $1.amount }
    }

    private var mismatch: Double {
        ((draftAmount - linesTotal) * 100).rounded() / 100
    }

    private var hasMismatch: Bool { abs(mismatch) >= 0.01 }

    private var addLineTitle: String {
        let sum = Fmt.signedMoney(mismatch, code: store.currency, fraction: true)
        return "Дописать строку на \(sum)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    totalsBlock
                    linesBlock
                    categoryBlock
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
            }

            footer
        }
        .frame(width: 720, height: 620)
        .onAppear {
            guard !loaded else { return }
            loaded = true
            draftLines = lines
            draftAmount = amount
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Чек")
                .font(.headline)
            Text(merchant.isEmpty
                 ? "Поправьте позиции и итог, если распозналось криво."
                 : "\(merchant) · поправьте позиции и итог, если распозналось криво.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    // MARK: Суммы

    private var totalsBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 18) {
                KeyValueRow(
                    key: "Сумма позиций",
                    value: Fmt.money(linesTotal, code: store.currency, fraction: true),
                    bold: true
                )
                KeyValueRow(
                    key: "Сумма операции",
                    value: Fmt.money(draftAmount, code: store.currency, fraction: true)
                )
                if hasMismatch {
                    KeyValueRow(
                        key: "Расхождение",
                        value: Fmt.signedMoney(mismatch, code: store.currency, fraction: true),
                        valueColor: Palette.amber,
                        bold: true
                    )
                }
            }

            HStack(spacing: 10) {
                Text("Итог операции")
                    .font(.callout)
                AmountField(title: "Сумма", value: $draftAmount, currency: store.currency)
                    .frame(width: 150)
            }

            if hasMismatch {
                HStack(spacing: 14) {
                    Button("Итог = сумма позиций") {
                        draftAmount = (linesTotal * 100).rounded() / 100
                    }
                    .buttonStyle(.link)

                    Button(addLineTitle) { addMissingLine() }
                        .buttonStyle(.link)
                }
                Text(mismatch > 0
                     ? "Позиций не хватает до суммы операции — распознаватель мог пропустить строку."
                     : "Позиций больше, чем сумма операции — возможно, строка задвоилась или это была скидка.")
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: Позиции

    private var linesBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Позиции: \(draftLines.count)")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button {
                    draftLines.append(ReceiptLine())
                } label: {
                    Label("Добавить строку", systemImage: "plus.circle")
                        .font(.caption)
                }
                .buttonStyle(.borderless)
            }

            if draftLines.isEmpty {
                Text("Строк нет. Добавьте вручную или прикрепите снимок чека заново.")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                    .padding(.vertical, 8)
            }

            ForEach($draftLines) { $line in
                ReceiptLineRow(line: $line) {
                    draftLines.removeAll { $0.id == line.id }
                }
                Divider().opacity(0.4)
            }
        }
    }

    /// Сводка по категориям — ровно в том виде, в каком чек потом раскрывается в списке операций.
    @ViewBuilder
    private var categoryBlock: some View {
        if !draftLines.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Как это ляжет в разбивку")
                    .font(.subheadline.weight(.semibold))
                ReceiptBreakdownView(lines: draftLines, currency: store.currency)
            }
            .padding(.top, 4)
        }
    }

    // MARK: Низ

    private var footer: some View {
        HStack {
            Button("Убрать чек", role: .destructive) {
                draftLines = []
                lines = []
                dismiss()
            }
            Spacer()
            Button("Отмена") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button("Сохранить") {
                save()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
        }
        .padding(20)
    }

    // MARK: Действия

    /// Строка на расхождение: честнее дописать недостающее, чем молча подогнать итог.
    private func addMissingLine() {
        var line = ReceiptLine()
        line.name = mismatch > 0 ? "Не распозналось" : "Поправка"
        line.quantity = 1
        line.amount = mismatch
        line.isDiscount = mismatch < 0
        draftLines.append(line)
    }

    private func save() {
        for line in draftLines {
            guard let productID = line.productID else { continue }
            store.rememberAlias(text: line.name, productID: productID)
        }
        lines = draftLines.filter { !($0.name.trimmingCharacters(in: .whitespaces).isEmpty && abs($0.amount) < 0.001) }
        amount = draftAmount
        dismiss()
    }
}
