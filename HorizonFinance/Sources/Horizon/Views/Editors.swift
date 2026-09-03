import SwiftUI

// MARK: - Операция

struct TransactionEditor: View {
    enum Mode {
        case create
        case edit(Txn)
    }

    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    var mode: Mode

    @State private var draft = Txn()
    @State private var loaded = false

    private var isEditing: Bool {
        if case .edit = mode { return true }
        return false
    }

    private var categories: [Category] { store.categories(for: draft.flow) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            Form {
                Picker("Тип", selection: $draft.flow) {
                    ForEach(MoneyFlow.allCases) { flow in
                        Text(flow.title).tag(flow)
                    }
                }
                .pickerStyle(.segmented)

                DatePicker("Дата", selection: $draft.date, displayedComponents: .date)

                AmountField(title: "Сумма", value: $draft.amount, currency: store.currency)

                Picker("Категория", selection: $draft.categoryID) {
                    Text("Без категории").tag(UUID?.none)
                    ForEach(categories) { category in
                        Text(category.displayName).tag(UUID?.some(category.id))
                    }
                }

                TextField("Заметка", text: $draft.note)

                if draft.flow == .expense {
                    let kind = store.data.categories.first(where: { $0.id == draft.categoryID })?.kind ?? .flexible
                    HStack(spacing: 6) {
                        Image(systemName: kind == .essential ? "lock.fill" : "sparkles")
                            .foregroundStyle(Palette.categoryColor(kind))
                        Text(kind == .essential
                             ? "Обязательная трата — не влияет на лимит свободных денег"
                             : "Свободная трата — уменьшает запас месяца")
                            .font(.caption)
                            .foregroundStyle(Palette.muted)
                    }
                }
            }
            .formStyle(.grouped)

            footer
        }
        .frame(width: 460)
        .onAppear {
            guard !loaded else { return }
            loaded = true
            if case .edit(let txn) = mode {
                draft = txn
            } else {
                draft.categoryID = store.categories(for: .expense).first?.id
            }
        }
        .onChange(of: draft.flow) { newFlow in
            let stillValid = store.data.categories.first(where: { $0.id == draft.categoryID })?.flow == newFlow
            if !stillValid {
                draft.categoryID = store.categories(for: newFlow).first?.id
            }
        }
    }

    private var header: some View {
        HStack {
            Text(isEditing ? "Изменить операцию" : "Новая операция")
                .font(.headline)
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
        .padding(.bottom, 4)
    }

    private var footer: some View {
        HStack {
            if isEditing {
                Button("Удалить", role: .destructive) {
                    store.deleteTransaction(draft)
                    dismiss()
                }
            }
            Spacer()
            Button("Отмена") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button(isEditing ? "Сохранить" : "Добавить") {
                if isEditing {
                    store.updateTransaction(draft)
                } else {
                    store.addTransaction(draft)
                }
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(draft.amount <= 0)
        }
        .padding(20)
    }
}

// MARK: - Цель

struct GoalEditor: View {
    enum Mode {
        case create
        case edit(Goal)
    }

    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    var mode: Mode

    @State private var draft = Goal()
    @State private var hasDeadline = false
    @State private var deadline = Date()
    @State private var loaded = false
    @State private var confirmDelete = false

    private let emojiChoices = ["🛟", "🚗", "🏡", "✈️", "💻", "🎓", "🩺", "💍", "🛠", "🎯"]

    private var isEditing: Bool {
        if case .edit = mode { return true }
        return false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(isEditing ? "Изменить цель" : "Новая цель")
                    .font(.headline)
                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 18)

            Form {
                Section {
                    TextField("Название", text: $draft.title)
                    emojiRow
                    colorRow
                }

                Section("Деньги") {
                    AmountField(title: "Цель", value: $draft.targetAmount, currency: store.currency)
                    AmountField(title: "Уже накоплено", value: $draft.startingAmount, currency: store.currency)
                    Text("«Уже накоплено» — то, что лежит на эту цель до начала учёта. Дальнейшие пополнения добавляются кнопкой «Пополнить».")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                }

                Section("Срок и приоритет") {
                    Toggle("Есть желаемый срок", isOn: $hasDeadline)
                    if hasDeadline {
                        DatePicker("Успеть к", selection: $deadline, displayedComponents: .date)
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text("Доля темпа")
                            Spacer()
                            Text(Fmt.percent(draft.share))
                                .foregroundStyle(Palette.muted)
                        }
                        Slider(value: $draft.share, in: 0...1, step: 0.05)
                        Text("Работает в режиме «параллельно, долями». В режиме «по очереди» цель финансируется целиком по приоритету.")
                            .font(.caption)
                            .foregroundStyle(Palette.muted)
                    }
                }

                Section("Заметка") {
                    TextField("Например: не трогать на поездки", text: $draft.note, axis: .vertical)
                        .lineLimit(2...4)
                }
            }
            .formStyle(.grouped)

            footer
        }
        .frame(width: 480)
        .onAppear {
            guard !loaded else { return }
            loaded = true
            if case .edit(let goal) = mode {
                draft = goal
                if let existing = goal.deadline {
                    hasDeadline = true
                    deadline = existing
                }
            } else {
                draft.colorHex = Palette.goalColors.randomElement() ?? "#4F8DF7"
                draft.priority = (store.data.goals.map { $0.priority }.max() ?? -1) + 1
            }
        }
        .alert("Удалить цель?", isPresented: $confirmDelete) {
            Button("Отмена", role: .cancel) { }
            Button("Удалить", role: .destructive) {
                store.deleteGoal(draft)
                dismiss()
            }
        } message: {
            Text("История пополнений этой цели тоже удалится. Операции по доходам и расходам останутся на месте.")
        }
    }

    private var emojiRow: some View {
        HStack(spacing: 6) {
            Text("Значок")
            Spacer()
            ForEach(emojiChoices, id: \.self) { emoji in
                Button {
                    draft.emoji = emoji
                } label: {
                    Text(emoji)
                        .font(.body)
                        .frame(width: 26, height: 26)
                        .background(
                            RoundedRectangle(cornerRadius: 6)
                                .fill(draft.emoji == emoji ? Palette.accent.opacity(0.25) : Color.primary.opacity(0.05))
                        )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var colorRow: some View {
        HStack(spacing: 8) {
            Text("Цвет")
            Spacer()
            ForEach(Palette.goalColors, id: \.self) { hex in
                Button {
                    draft.colorHex = hex
                } label: {
                    Circle()
                        .fill(Color(hex: hex))
                        .frame(width: 20, height: 20)
                        .overlay(
                            Circle()
                                .strokeBorder(Color.primary.opacity(draft.colorHex == hex ? 0.8 : 0), lineWidth: 2)
                        )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var footer: some View {
        HStack {
            if isEditing {
                Button("Удалить", role: .destructive) { confirmDelete = true }
            }
            Spacer()
            Button("Отмена") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button(isEditing ? "Сохранить" : "Добавить") {
                draft.deadline = hasDeadline ? deadline : nil
                if draft.title.trimmingCharacters(in: .whitespaces).isEmpty {
                    draft.title = "Новая цель"
                }
                if isEditing {
                    store.updateGoal(draft)
                } else {
                    store.addGoal(draft)
                }
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(draft.targetAmount <= 0)
        }
        .padding(20)
    }
}

// MARK: - Пополнение цели

struct ContributionEditor: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    var goal: Goal

    @State private var amount: Double = 0
    @State private var date = Date()
    @State private var note = ""
    @State private var isWithdrawal = false

    private var saved: Double { store.analytics.saved(for: goal) }
    private var remaining: Double { max(goal.targetAmount - saved, 0) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Text(goal.emoji)
                    .font(.title2)
                VStack(alignment: .leading, spacing: 1) {
                    Text(goal.title)
                        .font(.headline)
                    Text("накоплено \(Fmt.money(saved, code: store.currency)) из \(Fmt.money(goal.targetAmount, code: store.currency))")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                }
                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 18)

            Form {
                Picker("Операция", selection: $isWithdrawal) {
                    Text("Пополнить").tag(false)
                    Text("Снять").tag(true)
                }
                .pickerStyle(.segmented)

                AmountField(title: "Сумма", value: $amount, currency: store.currency)
                DatePicker("Дата", selection: $date, displayedComponents: .date)
                TextField("Заметка", text: $note)

                if !isWithdrawal && remaining > 0 {
                    Button("Внести остаток — \(Fmt.money(remaining, code: store.currency))") {
                        amount = remaining
                    }
                    .buttonStyle(.link)
                }
            }
            .formStyle(.grouped)

            HStack {
                Spacer()
                Button("Отмена") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button(isWithdrawal ? "Снять" : "Пополнить") {
                    let signed = isWithdrawal ? -abs(amount) : abs(amount)
                    store.addContribution(Contribution(goalID: goal.id, date: date, amount: signed, note: note))
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(amount <= 0)
            }
            .padding(20)
        }
        .frame(width: 440)
    }
}
