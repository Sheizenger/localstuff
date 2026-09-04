import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ReceiptImportView: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    private enum Stage: Equatable {
        case idle
        case scanning
        case review
        case failed(String)
    }

    @State private var stage: Stage = .idle
    @State private var receipt = ParsedReceipt()
    @State private var isTargeted = false
    @State private var splitFlexible = true
    @State private var updatePrices = true
    @State private var showRawText = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            switch stage {
            case .idle:
                dropZone
            case .scanning:
                scanningView
            case .failed(let message):
                failureView(message)
            case .review:
                reviewView
            }

            footer
        }
        .frame(width: 720, height: 640)
    }

    // MARK: Шапка

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Чек из магазина")
                .font(.headline)
            Text("Снимок, фото или PDF. Распознавание идёт на этом компьютере — файл никуда не отправляется.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    // MARK: Приём файла

    private var dropZone: some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "doc.viewfinder")
                .font(.system(size: 42, weight: .light))
                .foregroundStyle(isTargeted ? Palette.accent : Palette.muted)
            Text("Перетащите сюда чек")
                .font(.title3.weight(.medium))
            Text("PNG, JPEG, HEIC или PDF. QR TicketBAI, если он попал в кадр, даст точную дату и магазин.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            HStack(spacing: 10) {
                Button("Выбрать файл…") { pickFile() }
                    .buttonStyle(.borderedProminent)
                Button("Вставить из буфера") { pasteFromClipboard() }
            }
            .padding(.top, 4)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(
                    isTargeted ? Palette.accent : Color.primary.opacity(0.15),
                    style: StrokeStyle(lineWidth: 1.5, dash: [7, 5])
                )
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(isTargeted ? Palette.accent.opacity(0.06) : Color.clear)
                )
        )
        .padding(20)
        .onDrop(of: [.fileURL, .image, .pdf], isTargeted: $isTargeted) { providers in
            handleDrop(providers)
        }
    }

    private var scanningView: some View {
        VStack(spacing: 12) {
            Spacer()
            ProgressView()
            Text("Читаю чек…")
                .font(.callout)
                .foregroundStyle(Palette.muted)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func failureView(_ message: String) -> some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Palette.amber)
            Text(message)
                .font(.callout)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            Button("Попробовать другой файл") { stage = .idle }
                .buttonStyle(.borderedProminent)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: Проверка разбора

    private var reviewView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                summaryBlock
                if !receipt.warnings.isEmpty { warningsBlock }
                linesBlock
                optionsBlock
                rawTextBlock
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }

    private var summaryBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                TextField("Магазин", text: $receipt.merchantName)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 240)

                DatePicker("", selection: dateBinding, displayedComponents: .date)
                    .labelsHidden()
                    .frame(width: 130)

                Spacer()

                if let code = receipt.receiptCode {
                    Label(code, systemImage: "qrcode")
                        .font(.caption2)
                        .foregroundStyle(Palette.teal)
                        .lineLimit(1)
                }
            }

            HStack(spacing: 18) {
                KeyValueRow(key: "Сумма позиций", value: Fmt.money(receipt.linesTotal, code: store.currency, fraction: true), bold: true)
                KeyValueRow(
                    key: "Итог в чеке",
                    value: receipt.printedTotal.map { Fmt.money($0, code: store.currency, fraction: true) } ?? "не найден"
                )
                if let mismatch = receipt.mismatch, abs(mismatch) >= 0.05 {
                    KeyValueRow(
                        key: "Расхождение",
                        value: Fmt.signedMoney(mismatch, code: store.currency, fraction: true),
                        valueColor: Palette.amber,
                        bold: true
                    )
                }
            }

            if let mismatch = receipt.mismatch, abs(mismatch) >= 0.05 {
                Button("Считать верной сумму позиций") {
                    receipt.printedTotal = receipt.linesTotal
                }
                .buttonStyle(.link)
            }
        }
    }

    private var warningsBlock: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(Array(receipt.warnings.enumerated()), id: \.offset) { _, warning in
                Label(warning, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(Palette.amber)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var linesBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Позиции: \(receipt.lines.count)")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Text("категорию можно поправить — приложение запомнит")
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
            }

            ForEach($receipt.lines) { $line in
                receiptRow($line)
                Divider().opacity(0.4)
            }
        }
    }

    private func receiptRow(_ line: Binding<ReceiptLine>) -> some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                TextField("Название", text: line.name)
                    .textFieldStyle(.plain)
                    .font(.body)
                Text(line.wrappedValue.raw)
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Picker("", selection: productBinding(line)) {
                Text("не узнан").tag("")
                ForEach(BasketCatalog.products) { product in
                    Text("\(product.category.emoji) \(product.name)").tag(product.id)
                }
            }
            .labelsHidden()
            .frame(width: 190)

            TextField("", value: line.quantity, format: .number.precision(.fractionLength(0...3)))
                .textFieldStyle(.roundedBorder)
                .multilineTextAlignment(.trailing)
                .frame(width: 60)

            TextField("", value: line.amount, format: .number.precision(.fractionLength(2)))
                .textFieldStyle(.roundedBorder)
                .multilineTextAlignment(.trailing)
                .frame(width: 76)

            Button {
                receipt.lines.removeAll { $0.id == line.wrappedValue.id }
            } label: {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help("Убрать строку")
        }
        .padding(.vertical, 2)
    }

    private var optionsBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Toggle("Бытовое и алкоголь записать отдельной свободной тратой", isOn: $splitFlexible)
                .font(.callout)
            Text("В приложении лимит месяца съедают именно свободные траты. Если не разделять, весь чек уйдёт в обязательные «Продукты».")
                .font(.caption2)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)

            Toggle("Обновить цены корзины по этому чеку", isOn: $updatePrices)
                .font(.callout)
                .disabled(receipt.chainID == nil)
            Text(receipt.chainID == nil
                 ? "Сеть по чеку не опознана — цены корзины не тронем."
                 : "Цены с полки перебьют модельные для этой сети — корзина станет считать по вашим чекам.")
                .font(.caption2)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 4)
    }

    private var rawTextBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button(showRawText ? "Скрыть распознанный текст" : "Показать распознанный текст") {
                showRawText.toggle()
            }
            .buttonStyle(.link)

            if showRawText {
                Text(receipt.rawText.joined(separator: "\n"))
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(Palette.muted)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                    .background(
                        RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04))
                    )
            }
        }
    }

    // MARK: Низ

    private var footer: some View {
        HStack {
            if stage == .review {
                Button("Другой чек") { stage = .idle }
            }
            Spacer()
            Button("Отмена") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button(commitTitle) { commit() }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(stage != .review || receipt.lines.isEmpty)
        }
        .padding(20)
    }

    private var commitTitle: String {
        guard stage == .review else { return "Записать" }
        return "Записать \(Fmt.money(receipt.amountToRecord, code: store.currency, fraction: true))"
    }

    // MARK: Привязки

    private var dateBinding: Binding<Date> {
        Binding(
            get: { receipt.date ?? Date() },
            set: { receipt.date = $0 }
        )
    }

    /// Выбор товара из справочника: заодно чинит категорию и учит разбор на будущее.
    private func productBinding(_ line: Binding<ReceiptLine>) -> Binding<String> {
        Binding(
            get: { line.wrappedValue.productID ?? "" },
            set: { newValue in
                if newValue.isEmpty {
                    line.wrappedValue.productID = nil
                    return
                }
                guard let product = BasketCatalog.product(id: newValue) else { return }
                line.wrappedValue.productID = product.id
                line.wrappedValue.category = product.category
                store.rememberAlias(text: line.wrappedValue.name, productID: product.id)
            }
        )
    }

    // MARK: Действия

    private func pickFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image, .pdf]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        handle(url: url)
    }

    private func pasteFromClipboard() {
        let pasteboard = NSPasteboard.general
        if let image = NSImage(pasteboard: pasteboard) {
            handle(image: image)
            return
        }
        if let urls = pasteboard.readObjects(forClasses: [NSURL.self], options: nil) as? [URL],
           let url = urls.first {
            handle(url: url)
            return
        }
        stage = .failed("В буфере обмена нет ни картинки, ни файла.")
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }

        if provider.canLoadObject(ofClass: NSImage.self) {
            provider.loadObject(ofClass: NSImage.self) { object, _ in
                guard let image = object as? NSImage else { return }
                DispatchQueue.main.async { self.handle(image: image) }
            }
            return true
        }

        provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
            guard let data = data,
                  let path = String(data: data, encoding: .utf8),
                  let url = URL(string: path)
            else { return }
            DispatchQueue.main.async { self.handle(url: url) }
        }
        return true
    }

    private func handle(url: URL) {
        run { try ReceiptScanner.scan(url: url) }
    }

    private func handle(image: NSImage) {
        run { try ReceiptScanner.scan(image: image) }
    }

    /// Распознавание идёт в фоне: на большом снимке это несколько секунд.
    private func run(_ work: @escaping () throws -> ScannedDocument) {
        stage = .scanning
        let aliases = store.data.receiptAliases
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let document = try work()
                let parsed = ReceiptParser.parse(document, aliases: aliases)
                DispatchQueue.main.async {
                    self.receipt = parsed
                    self.stage = .review
                }
            } catch {
                DispatchQueue.main.async {
                    self.stage = .failed(error.localizedDescription)
                }
            }
        }
    }

    private func commit() {
        for line in receipt.lines {
            if let productID = line.productID {
                store.rememberAlias(text: line.name, productID: productID)
            }
        }
        store.importReceipt(receipt, splitFlexible: splitFlexible, updateBasketPrices: updatePrices)
        dismiss()
    }
}
