import SwiftUI

/// Редактор шаблона повторяющейся операции.
struct RecurringEditor: View {
    enum Mode {
        case create
        case edit(RecurringRule)
    }

    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    var mode: Mode

    @State private var draft = RecurringRule()
    @State private var hasEnd = false
    @State private var endDate = Date()
    @State private var loaded = false

    private var isEditing: Bool {
        if case .edit = mode { return true }
        return false
    }

    private var categories: [Category] { store.categories(for: draft.flow) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(isEditing ? "Изменить шаблон" : "Новый шаблон")
                    .font(.headline)
                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 18)

            Form {
                Section {
                    TextField("Название", text: $draft.title)

                    Picker("Тип", selection: $draft.flow) {
                        ForEach(MoneyFlow.allCases) { flow in
                            Text(flow.title).tag(flow)
                        }
                    }
                    .pickerStyle(.segmented)

                    AmountField(title: "Сумма", value: $draft.amount, currency: store.currency)

                    Picker("Категория", selection: $draft.categoryID) {
                        Text("Без категории").tag(UUID?.none)
                        ForEach(categories) { category in
                            Text(category.displayName).tag(UUID?.some(category.id))
                        }
                    }
                }

                Section("Когда") {
                    Picker("Периодичность", selection: $draft.unit) {
                        ForEach(RecurrenceUnit.allCases) { unit in
                            Text(unit.title).tag(unit)
                        }
                    }

                    switch draft.unit {
                    case .month:
                        Stepper(value: $draft.dayOfMonth, in: 1...31) {
                            Text("День месяца: \(draft.dayOfMonth)")
                        }
                        Stepper(value: $draft.interval, in: 1...12) {
                            Text(draft.interval == 1 ? "Каждый месяц" : "Раз в \(draft.interval) мес.")
                        }
                    case .week:
                        Picker("День недели", selection: $draft.weekday) {
                            Text("Понедельник").tag(2)
                            Text("Вторник").tag(3)
                            Text("Среда").tag(4)
                            Text("Четверг").tag(5)
                            Text("Пятница").tag(6)
                            Text("Суббота").tag(7)
                            Text("Воскресенье").tag(1)
                        }
                        Stepper(value: $draft.interval, in: 1...8) {
                            Text(draft.interval == 1 ? "Каждую неделю" : "Раз в \(draft.interval) нед.")
                        }
                    case .year:
                        Picker("Месяц", selection: $draft.monthOfYear) {
                            ForEach(1...12, id: \.self) { month in
                                Text(Cal.ru.monthSymbols[month - 1].capitalizedFirst).tag(month)
                            }
                        }
                        Stepper(value: $draft.dayOfMonth, in: 1...31) {
                            Text("День: \(draft.dayOfMonth)")
                        }
                    }

                    DatePicker("Действует с", selection: $draft.startDate, displayedComponents: .date)
                    Toggle("Есть дата окончания", isOn: $hasEnd)
                    if hasEnd {
                        DatePicker("Заканчивается", selection: $endDate, displayedComponents: .date)
                    }

                    if draft.dayOfMonth > 28 && draft.unit != .week {
                        Text("В коротких месяцах операция встанет на последний день — 30 или 28 числа.")
                            .font(.caption)
                            .foregroundStyle(Palette.muted)
                    }
                }

                Section("Поведение") {
                    Toggle("Создавать операции автоматически", isOn: $draft.autoCreate)
                    Text(draft.autoCreate
                         ? "Операции появятся сами при запуске приложения, как только наступит дата."
                         : "Шаблон будет только показывать ожидаемое на «Обзоре», но ничего не создаст.")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                    Toggle("Шаблон активен", isOn: $draft.isActive)
                    TextField("Заметка к операции", text: $draft.note)
                }

                if let next = RecurrenceEngine.next(for: previewRule) {
                    Section("Проверка") {
                        KeyValueRow(
                            key: "Следующее срабатывание",
                            value: Fmt.dayShort.string(from: next),
                            bold: true
                        )
                        Text(previewRule.scheduleTitle)
                            .font(.caption)
                            .foregroundStyle(Palette.muted)
                    }
                }
            }
            .formStyle(.grouped)

            footer
        }
        .frame(width: 480, height: 620)
        .onAppear {
            guard !loaded else { return }
            loaded = true
            if case .edit(let rule) = mode {
                draft = rule
                if let end = rule.endDate {
                    hasEnd = true
                    endDate = end
                }
            } else {
                draft.dayOfMonth = Cal.ru.component(.day, from: Date())
            }
        }
        .onChange(of: draft.flow) { newFlow in
            let stillValid = store.data.categories.first(where: { $0.id == draft.categoryID })?.flow == newFlow
            if !stillValid {
                draft.categoryID = store.categories(for: newFlow).first?.id
            }
        }
    }

    /// Копия черновика с учётом переключателя даты окончания — для предпросмотра.
    private var previewRule: RecurringRule {
        var rule = draft
        rule.endDate = hasEnd ? endDate : nil
        rule.isActive = true
        return rule
    }

    private var footer: some View {
        HStack {
            if isEditing {
                Button("Удалить", role: .destructive) {
                    store.deleteRule(draft)
                    dismiss()
                }
            }
            Spacer()
            Button("Отмена") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button(isEditing ? "Сохранить" : "Добавить") {
                draft.endDate = hasEnd ? endDate : nil
                if draft.title.trimmingCharacters(in: .whitespaces).isEmpty {
                    draft.title = draft.flow == .income ? "Регулярный доход" : "Регулярный расход"
                }
                if isEditing {
                    store.updateRule(draft)
                } else {
                    store.addRule(draft)
                }
                store.applyRecurringRules()
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(draft.amount <= 0)
        }
        .padding(20)
    }
}
