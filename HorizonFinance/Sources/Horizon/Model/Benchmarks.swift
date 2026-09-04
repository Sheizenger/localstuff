import Foundation

/// Внешний ориентир: сколько тратят другие домохозяйства по официальной статистике.
struct SpendingBenchmark: Identifiable, Hashable {
    let id: String
    let title: String
    /// Расход в месяц на домохозяйство, если показатель считается на домохозяйство.
    let perHousehold: Double?
    /// Расход в месяц на человека, если показатель считается на человека.
    let perPerson: Double?
    /// Средний размер домохозяйства, к которому относится показатель.
    let householdSize: Double?
    /// Что именно входит в показатель — важно, чтобы не сравнивать разное.
    let scope: String
    let period: String
    let source: String
    let url: String

    /// Приведение показателя к вашей семье: столько тратило бы среднее домохозяйство её размера.
    func expected(forPeople people: Int) -> Double {
        let count = Double(max(people, 1))
        if let perPerson = perPerson {
            return perPerson * count
        }
        guard let perHousehold = perHousehold else { return 0 }
        guard let size = householdSize, size > 0 else { return perHousehold }
        // Домохозяйство меньше среднего тратит меньше, но не строго пропорционально:
        // часть расходов делится на всех, поэтому берём корневое сглаживание.
        let scale = pow(count / size, 0.85)
        return perHousehold * scale
    }
}

enum BasketBenchmarks {

    /// Ориентиры пока собраны только для Испании — для остальных стран их честнее не показывать,
    /// чем показывать выдуманные.
    static func forCountry(_ countryID: String) -> [SpendingBenchmark] {
        countryID == "ES" ? spain : []
    }

    static let spain: [SpendingBenchmark] = [
        SpendingBenchmark(
            id: "ine_epf_2025",
            title: "Среднее домохозяйство Испании",
            perHousehold: 5626.0 / 12.0,
            perPerson: nil,
            householdSize: 2.5,
            scope: "еда и безалкогольные напитки, без бытовой химии и алкоголя",
            period: "2025",
            source: "INE, Encuesta de Presupuestos Familiares",
            url: "https://www.ine.es/dyngs/Prensa/EPF2025.htm"
        ),
        SpendingBenchmark(
            id: "mercasa_2025",
            title: "Средний человек в Испании",
            perHousehold: nil,
            perPerson: 1787.0 / 12.0,
            householdSize: nil,
            scope: "продукты для дома, «cesta de la compra»",
            period: "2025",
            source: "Mercasa, «Alimentación en España»",
            url: "https://www.mercasa.es/los-hogares-espanoles-dedican-1-787-euros-a-la-cesta-de-la-compra-de-media-por-persona-y-ano-segun-el-informe-alimentacion-en-espana-editado-por-mercasa/"
        )
    ]

    /// Сколько евро из каждых 100 евро всех расходов домохозяйства уходит на еду.
    static let foodShareOfBudget: Double = 0.16

    /// Строка структуры расходов: сколько евро из каждых 100 евро всех расходов уходит на эту группу.
    struct FoodShareItem: Identifiable, Hashable {
        let name: String
        let perHundred: Double
        var id: String { name }
    }

    /// Структура продуктовых расходов среднего домохозяйства.
    static let structure: [FoodShareItem] = [
        FoodShareItem(name: "Мясо", perHundred: 3.6),
        FoodShareItem(name: "Хлеб и крупы", perHundred: 2.1),
        FoodShareItem(name: "Молоко, сыр, яйца", perHundred: 2.1),
        FoodShareItem(name: "Рыба", perHundred: 1.7),
        FoodShareItem(name: "Овощи и картофель", perHundred: 1.7),
        FoodShareItem(name: "Фрукты", perHundred: 1.7)
    ]

    static let structureSource = "INE, Encuesta de Presupuestos Familiares, 2025"
}
