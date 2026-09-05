import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// Импорт выписки банка: один файл — весь месяц операций.
struct StatementImportView: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    private enum Stage: Equatable {
        case idle
        case parsing
        case review
        case failed(String)
    }

    @State private var stage: Stage = .idle
    @State private var statement = ParsedStatement()
    @State private var isTargeted = false
    @State private var hideDuplicates = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            switch stage {
            case .idle:
                dropZone
            case .parsing:
                progressView
            case .failed(let message):
                failureView(message)
            case .review:
                reviewView
            }

            footer
        }
        .frame(width: 860, height: 660)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Выписка из банка")
                .font(.headline)
            Text("CSV из личного кабинета: BBVA, Santander, Kutxabank, Openbank и другие. Файл читается на этом компьютере.")
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
            Image(systemName: "tablecells")
                .font(.system(size: 42, weight: .light))
                .foregroundStyle(isTargeted ? Palette.accent : Palette.muted)
            Text("Перетащите файл выписки")
                .font(.title3.weight(.medium))
            Text("Колонки определяются сами: дата, назначение платежа и сумма. Формат чисел — испанский или международный, оба понимаются.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 460)
            Button("Выбрать файл…") { pickFile() }
                .buttonStyle(.borderedProminent)
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
        )
        .padding(20)
        .onDrop(of: [.fileURL], isTargeted: $isTargeted) { providers in
            handleDrop(providers)
        }
    }

    private var progressView: some View {
        VStack(spacing: 12) {
            Spacer()
            ProgressView()
            Text("Разбираю выписку…")
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
                .frame(maxWidth: 440)
            Button("Выбрать другой файл") { stage = .idle }
                .buttonStyle(.borderedProminent)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: Проверка

    private var visibleRows: [StatementRow] {
        hideDuplicates ? statement.rows.filter { !$0.isDuplicate } : statement.rows
    }

    private var reviewView: some View {
        VStack(alignment: .leading, spacing: 10) {
            summaryLine

            if !statement.warnings.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(statement.warnings.enumerated()), id: \.offset) { _, warning in
                        Label(warning, systemImage: "info.circle")
                            .font(.caption)
                            .foregroundStyle(Palette.muted)
                    }
                }
            }

            HStack(spacing: 12) {
                Button("Отметить все") { setAll(true) }
                    .buttonStyle(.link)
                Button("Снять все") { setAll(false) }
                    .buttonStyle(.link)
                Toggle("Скрыть дубликаты", isOn: $hideDuplicates)
                    .toggleStyle(.checkbox)
                    .font(.caption)
                Spacer()
                Text(statement.columnsNote)
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
            }

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach($statement.rows) { $row in
                        if !hideDuplicates || !row.isDuplicate {
                            rowView($row)
                            Divider().opacity(0.35)
                        }
                    }
                }
            }
            .frame(maxHeight: .infinity)
        }
        .padding(.horizontal, 20)
    }

    private var summaryLine: some View {
        HStack(spacing: 20) {
            KeyValueRow(key: "Строк", value: "\(statement.rows.count)", bold: true)
            KeyValueRow(key: "Выбрано", value: "\(statement.rows.filter { $0.include }.count)", bold: true)
            KeyValueRow(key: "Поступления", value: Fmt.money(statement.incomeTotal, code: store.currency), valueColor: Palette.green)
            KeyValueRow(key: "Расходы", value: Fmt.money(statement.expenseTotal, code: store.currency), valueColor: Palette.red)
            let duplicates = statement.rows.filter { $0.isDuplicate }.count
            if duplicates > 0 {
                KeyValueRow(key: "Похоже на дубли", value: "\(duplicates)", valueColor: Palette.amber)
            }
        }
    }

    private func rowView(_ row: Binding<StatementRow>) -> some View {
        let value = row.wrappedValue
        return HStack(spacing: 10) {
            Toggle("", isOn: row.include)
                .labelsHidden()
                .toggleStyle(.checkbox)

            Text(Fmt.dayShort.string(from: value.date))
                .font(.caption.monospacedDigit())
                .foregroundStyle(Palette.muted)
                .frame(width: 96, alignment: .leading)

            VStack(alignment: .leading, spacing: 1) {
                Text(value.details)
                    .font(.subheadline)
                    .lineLimit(1)
                if value.isDuplicate {
                    Text("такая операция уже есть — по дате и сумме")
                        .font(.caption2)
                        .foregroundStyle(Palette.amber)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Picker("", selection: categoryBinding(row)) {
                Text("без категории").tag(UUID?.none)
                ForEach(store.categories(for: value.flow)) { category in
                    Text(category.displayName).tag(UUID?.some(category.id))
                }
            }
            .labelsHidden()
            .frame(width: 190)

            Text(Fmt.signedMoney(value.amount, code: store.currency, fraction: true))
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(value.amount >= 0 ? Palette.green : Palette.ink)
                .frame(width: 96, alignment: .trailing)
        }
        .padding(.vertical, 4)
        .opacity(value.include ? 1 : 0.45)
    }

    private func categoryBinding(_ row: Binding<StatementRow>) -> Binding<UUID?> {
        Binding(
            get: { row.wrappedValue.categoryID },
            set: { newValue in
                row.wrappedValue.categoryID = newValue
                if let newValue = newValue {
                    store.rememberMerchant(details: row.wrappedValue.details, categoryID: newValue)
                }
            }
        )
    }

    // MARK: Низ

    private var footer: some View {
        HStack {
            if stage == .review {
                Button("Другой файл") { stage = .idle }
            }
            Spacer()
            Button("Отмена") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button(commitTitle) {
                store.importStatement(rows: statement.rows)
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(stage != .review || statement.rows.allSatisfy { !$0.include })
        }
        .padding(20)
    }

    private var commitTitle: String {
        let count = statement.rows.filter { $0.include }.count
        return count > 0 ? "Записать операций: \(count)" : "Записать"
    }

    // MARK: Действия

    private func setAll(_ value: Bool) {
        for index in statement.rows.indices {
            if value && statement.rows[index].isDuplicate { continue }
            statement.rows[index].include = value
        }
    }

    private func pickFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.commaSeparatedText, .tabSeparatedText, .plainText, .text]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        handle(url: url)
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
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
        stage = .parsing
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let text = try StatementParser.loadText(url: url)
                let parsed = StatementParser.parse(text: text)
                DispatchQueue.main.async {
                    if parsed.rows.isEmpty {
                        self.stage = .failed(parsed.warnings.first ?? "Операции не найдены.")
                    } else {
                        self.statement = self.store.prepare(parsed)
                        self.stage = .review
                    }
                }
            } catch {
                DispatchQueue.main.async {
                    self.stage = .failed(error.localizedDescription)
                }
            }
        }
    }
}
