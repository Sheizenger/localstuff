import Foundation

/// Данные лежат в обычном JSON-файле — его легко скопировать, положить в облако или открыть глазами.
enum Persistence {

    static let folderName = "Horizon"
    static let fileName = "horizon-data.json"

    static var folderURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser
        return base.appendingPathComponent(folderName, isDirectory: true)
    }

    static var fileURL: URL {
        folderURL.appendingPathComponent(fileName)
    }

    static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    static func load() -> AppData? {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return nil }
        do {
            let raw = try Data(contentsOf: fileURL)
            return try makeDecoder().decode(AppData.self, from: raw)
        } catch {
            // Данные не должны теряться из-за одной кривой записи: откладываем файл в сторону.
            let backup = folderURL.appendingPathComponent("horizon-data-broken-\(Int(Date().timeIntervalSince1970)).json")
            try? FileManager.default.moveItem(at: fileURL, to: backup)
            NSLog("Horizon: не удалось прочитать данные (\(error.localizedDescription)), файл сохранён как \(backup.lastPathComponent)")
            return nil
        }
    }

    @discardableResult
    static func save(_ data: AppData) -> Bool {
        do {
            try FileManager.default.createDirectory(at: folderURL, withIntermediateDirectories: true)
            let raw = try makeEncoder().encode(data)
            try raw.write(to: fileURL, options: .atomic)
            return true
        } catch {
            NSLog("Horizon: не удалось сохранить данные — \(error.localizedDescription)")
            return false
        }
    }

    // MARK: Резервные копии

    static var backupsURL: URL {
        folderURL.appendingPathComponent("Backups", isDirectory: true)
    }

    /// Сколько копий держим: раз в неделю — это около двух месяцев истории.
    static let backupsToKeep = 8

    /// Копии, от свежей к старой. Имя файла заканчивается датой, поэтому сортировка
    /// по имени и есть сортировка по времени.
    static func backups() -> [URL] {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: backupsURL,
            includingPropertiesForKeys: [.contentModificationDateKey]
        )) ?? []
        return files
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
    }

    static func latestBackupDate() -> Date? {
        guard let newest = backups().first else { return nil }
        let values = try? newest.resourceValues(forKeys: [.contentModificationDateKey])
        return values?.contentModificationDate
    }

    /// Копия с сегодняшней датой в имени: несколько запусков за день не плодят файлы.
    @discardableResult
    static func makeBackup(_ data: AppData, now: Date = Date()) -> URL? {
        do {
            try FileManager.default.createDirectory(at: backupsURL, withIntermediateDirectories: true)
            let url = backupsURL.appendingPathComponent("horizon-\(Fmt.stampKey.string(from: now)).json")
            let raw = try makeEncoder().encode(data)
            try raw.write(to: url, options: .atomic)
            pruneBackups()
            return url
        } catch {
            NSLog("Horizon: не удалось сделать резервную копию — \(error.localizedDescription)")
            return nil
        }
    }

    static func pruneBackups() {
        for url in backups().dropFirst(backupsToKeep) {
            try? FileManager.default.removeItem(at: url)
        }
    }

    static func export(_ data: AppData, to url: URL) throws {
        let raw = try makeEncoder().encode(data)
        try raw.write(to: url, options: .atomic)
    }

    static func importData(from url: URL) throws -> AppData {
        let raw = try Data(contentsOf: url)
        return try makeDecoder().decode(AppData.self, from: raw)
    }
}
