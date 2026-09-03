import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct SettingsView: View {
    @EnvironmentObject private var store: Store

    @State private var confirmReset = false
    @State private var confirmDemo = false
    @State private var message: String? = nil

    private let currencies = ["EUR", "USD", "RUB", "GBP", "PLN", "GEL", "TRY", "RSD"]

    private var profile: Binding<Profile> { $store.data.profile }

    var body: some View {
        PageScroll {
            moneyCard
            planCard
            paceCard
            categoriesCard
            dataCard
        }
        .alert("Сбросить все данные?", isPresented: $confirmReset) {
            Button("Отмена", role: .cancel) { }
            Button("Сбросить", role: .destructive) { store.resetAll() }
        } message: {
            Text("Операции, цели и пополнения будут удалены. Останутся стандартные категории и пустая подушка.")
        }
        .alert("Заменить данные демо-примером?", isPresented: $confirmDemo) {
            Button("Отмена", role: .cancel) { }
            Button("Загрузить демо", role: .destructive) { store.loadDemoData() }
        } message: {
            Text("Текущие операции и цели будут заменены семью месяцами вымышленной истории. Сделайте экспорт, если данные важны.")
        }
    }

    // MARK: Валюта

    private var moneyCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(title: "Деньги", subtitle: "валюта и стартовая точка учёта")
            HStack(spacing: 24) {
                Picker("Валюта", selection: profile.currencyCode) {
                    ForEach(currencies, id: \.self) { code in
                        Text("\(Fmt.symbol(for: code))  \(code)").tag(code)
                    }
                }
                .frame(width: 200)

                HStack {
                    Text("Остаток на счетах на старте")
                    AmountField(title: "0", value: profile.openingBalance, currency: store.currency)
                        .frame(width: 160)
                }
            }
            Text("Стартовый остаток — это деньги, которые уже лежали на счетах, когда вы начали вести учёт. То, что уже отложено на конкретные цели, указывается в самой цели.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .cardStyle()
    }

    // MARK: План месяца

    private var planCard: some View {
        let p = store.data.profile
        let potential = p.plannedIncome - p.essentialsPlan - p.flexibleLimit
        return VStack(alignment: .leading, spacing: 14) {
            SectionTitle(title: "План месяца", subtitle: "решение о накоплениях принимается до трат, а не в конце месяца")

            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                GridRow {
                    Text("Ожидаемый доход")
                    AmountField(title: "0", value: profile.plannedIncome, currency: store.currency).frame(width: 170)
                    Text("зарплата и то, на что реально можно рассчитывать")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
                GridRow {
                    Text("Обязательные расходы")
                    AmountField(title: "0", value: profile.essentialsPlan, currency: store.currency).frame(width: 170)
                    Text("аренда, счета, продукты, транспорт")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
                GridRow {
                    Text("Лимит свободных трат")
                    AmountField(title: "0", value: profile.flexibleLimit, currency: store.currency).frame(width: 170)
                    Text("фонд на «всякое» — именно он уходит в красную зону")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
                GridRow {
                    Text("План откладывать")
                    AmountField(title: "0", value: profile.savingsPlan, currency: store.currency).frame(width: 170)
                    Text("сумма, которая уходит со счёта в день зарплаты")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
            }

            Divider()

            HStack(spacing: 20) {
                KeyValueRow(
                    key: "Потенциальный остаток по плану",
                    value: "\(Fmt.money(potential, code: store.currency))/мес.",
                    valueColor: potential >= p.savingsPlan ? Palette.green : Palette.amber,
                    bold: true
                )
            }
            if potential < p.savingsPlan {
                Label("План откладывать больше, чем остаётся по расчёту. Либо уменьшите лимит свободных трат, либо признайте реальный темп — иначе прогноз будет врать.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(Palette.amber)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .cardStyle()
    }

    // MARK: Темп

    private var paceCard: some View {
        let pace = store.analytics.pace
        return VStack(alignment: .leading, spacing: 14) {
            SectionTitle(title: "Темп и прогноз", subtitle: "на основе чего считаются сроки достижения целей")

            Picker("Как считать темп", selection: profile.paceMode) {
                ForEach(PaceMode.allCases) { mode in
                    Text(mode.title).tag(mode)
                }
            }
            .frame(width: 380)

            if store.data.profile.paceMode == .manual {
                HStack {
                    Text("Темп вручную")
                    AmountField(title: "0", value: profile.manualPace, currency: store.currency)
                        .frame(width: 170)
                    Text("в месяц")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
            }

            Label("Распределение темпа задаётся у каждой цели отдельно — на вкладке «Цели»: часть целей копится параллельно долями, часть стоит в очереди.",
                  systemImage: "arrow.triangle.branch")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)

            Divider()

            KeyValueRow(
                key: "Текущий расчётный темп",
                value: "\(Fmt.money(pace.value, code: store.currency))/мес. · \(pace.isPlanned ? "план из настроек" : pace.basis)",
                bold: true
            )
            Text("Темп считается по завершённым месяцам: доход минус расходы. Текущий, ещё не прожитый месяц в расчёт не берётся — иначе прогноз скакал бы каждый день.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .cardStyle()
    }

    // MARK: Категории

    private var categoriesCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionTitle(title: "Категории", subtitle: "«обязательные» не трогают лимит, «свободные» — трогают")
                Spacer()
                Menu("Добавить") {
                    Button("Категория расхода") {
                        store.addCategory(Category(name: "Новая категория", emoji: "•", flow: .expense, kind: .flexible))
                    }
                    Button("Категория дохода") {
                        store.addCategory(Category(name: "Новый доход", emoji: "•", flow: .income, kind: .essential))
                    }
                }
                .frame(width: 130)
            }

            ForEach($store.data.categories) { $category in
                HStack(spacing: 10) {
                    TextField("", text: $category.emoji)
                        .frame(width: 44)
                        .multilineTextAlignment(.center)
                    TextField("Название", text: $category.name)
                        .frame(maxWidth: 260)
                    if category.flow == .expense {
                        Picker("", selection: $category.kind) {
                            ForEach(SpendKind.allCases) { kind in
                                Text(kind.title).tag(kind)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 150)
                    } else {
                        Text("Доход")
                            .font(.caption)
                            .foregroundStyle(Palette.green)
                            .frame(width: 150, alignment: .leading)
                    }
                    Spacer()
                    Button {
                        store.deleteCategory(category)
                    } label: {
                        Image(systemName: "trash")
                    }
                    .buttonStyle(.borderless)
                    .help("Удалить категорию — операции останутся, но потеряют её")
                }
            }
        }
        .cardStyle()
    }

    // MARK: Данные

    private var dataCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: "Данные", subtitle: "всё лежит на вашем компьютере, в обычном JSON")

            KeyValueRow(key: "Файл", value: Persistence.fileURL.path)
            if let saved = store.lastSavedAt {
                KeyValueRow(key: "Последнее сохранение", value: Fmt.dayShort.string(from: saved) + ", " + timeString(saved))
            }
            if let error = store.saveError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(Palette.red)
            }
            if let message = message {
                Label(message, systemImage: "checkmark.circle.fill")
                    .font(.caption)
                    .foregroundStyle(Palette.green)
            }

            HStack(spacing: 10) {
                Button("Показать в Finder") {
                    store.saveNow()
                    NSWorkspace.shared.activateFileViewerSelecting([Persistence.fileURL])
                }
                Button("Экспорт…") { exportData() }
                Button("Импорт…") { importData() }
                Spacer()
                Button("Демо-данные") { confirmDemo = true }
                Button("Сбросить всё", role: .destructive) { confirmReset = true }
            }
        }
        .cardStyle()
    }

    private func timeString(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Fmt.locale
        f.dateFormat = "HH:mm"
        return f.string(from: date)
    }

    private func exportData() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "horizon-backup.json"
        panel.allowedContentTypes = [.json]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try Persistence.export(store.data, to: url)
            message = "Экспорт сохранён: \(url.lastPathComponent)"
        } catch {
            message = nil
            NSSound.beep()
        }
    }

    private func importData() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let imported = try Persistence.importData(from: url)
            store.replace(with: imported)
            message = "Данные загружены из \(url.lastPathComponent)"
        } catch {
            message = nil
            NSSound.beep()
        }
    }
}
