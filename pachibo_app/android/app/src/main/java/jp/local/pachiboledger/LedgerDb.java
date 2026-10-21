package jp.local.pachiboledger;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

final class LedgerDb extends SQLiteOpenHelper {
    LedgerDb(Context context) { this(context, "ledger.db"); }
    LedgerDb(Context context, String name) { super(context, name, null, 7); }

    @Override public void onConfigure(SQLiteDatabase db) { db.setForeignKeyConstraintsEnabled(true); }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE records (id TEXT PRIMARY KEY, date TEXT NOT NULL, hall TEXT NOT NULL, kind TEXT NOT NULL, machine TEXT NOT NULL, machine_number TEXT, investment_yen INTEGER NOT NULL, recovery_yen INTEGER NOT NULL, profit_yen INTEGER NOT NULL, duration TEXT, memo TEXT, tag_ids TEXT NOT NULL, match_status TEXT, source_item_id TEXT, legacy_tag_bits TEXT)");
        db.execSQL("CREATE INDEX records_date ON records(date)");
        db.execSQL("CREATE TABLE tags (source_id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT, priority TEXT)");
        SessionStore.createTables(db);
        createArchives(db);
        SessionStore.createHistory(db);
        AccountStore.createTables(db);
        Catalog.createTables(db);
        CalendarEventStore.createTables(db);
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion < 2) SessionStore.createTables(db);
        if (oldVersion < 3) createArchives(db);
        if (oldVersion < 4) SessionStore.createHistory(db);
        if (oldVersion < 5) AccountStore.createTables(db);
        if (oldVersion < 6) Catalog.createTables(db);
        if (oldVersion < 7) CalendarEventStore.createTables(db);
    }

    private static void createArchives(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE source_archives (id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)");
    }

    static ContentValues values(JSONObject row) {
        ContentValues v = new ContentValues();
        for (String key : new String[]{"id", "date", "hall", "kind", "machine", "machine_number", "duration", "memo", "match_status", "source_item_id", "legacy_tag_bits"}) {
            if (row.has(key) && row.isNull(key)) v.putNull(key); else v.put(key, row.optString(key, ""));
        }
        for (String key : new String[]{"investment_yen", "recovery_yen", "profit_yen"}) v.put(key, row.optLong(key, 0));
        v.put("tag_ids", row.optJSONArray("tag_ids") == null ? "[]" : row.optJSONArray("tag_ids").toString());
        return v;
    }

    int importJson(JSONObject input) throws JSONException {
        String format = input.optString("format");
        if (!"pachibo-ledger-v1".equals(format) && !"pachibo-ledger-v2".equals(format) && !"pachibo-ledger-v3".equals(format) && !"pachibo-ledger-v4".equals(format) && !"pachibo-ledger-v5".equals(format) && !"pachibo-ledger-v6".equals(format) && !"pachibo-ledger-v7".equals(format)) throw new JSONException("Unknown backup format");
        JSONArray rows = input.getJSONArray("records");
        JSONArray tags = input.optJSONArray("tags");
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            if (tags != null) for (int i = 0; i < tags.length(); i++) {
                JSONObject tag = tags.getJSONObject(i);
                ContentValues v = new ContentValues();
                for (String key : new String[]{"source_id", "name", "type", "priority"}) {
                    if (tag.has(key) && tag.isNull(key)) v.putNull(key); else v.put(key, tag.optString(key, ""));
                }
                insertOrMatch(db, "tags", "source_id", v);
            }
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.getJSONObject(i);
                if (row.optString("id").isEmpty() || row.optString("date").isEmpty()) throw new JSONException("Record missing ID or date at " + i);
                ContentValues record=values(row);
                if("pachibo-ledger-v1".equals(format))insertOrClassifyPcbRecord(db,record);
                else insertOrMatch(db,"records","id",record);
                if("pachibo-ledger-v1".equals(format))importLegacyTimes(db,row);
            }
            if (!"pachibo-ledger-v1".equals(format)) {
                String[] tables = "pachibo-ledger-v7".equals(format) ? new String[]{"accounts", "sessions", "operations", "transfers", "source_archives", "edit_history", "catalog", "record_details", "calendar_events"} : "pachibo-ledger-v6".equals(format) ? new String[]{"accounts", "sessions", "operations", "transfers", "source_archives", "edit_history", "catalog", "record_details"} : "pachibo-ledger-v5".equals(format) ? new String[]{"accounts", "sessions", "operations", "transfers", "source_archives", "edit_history"} : "pachibo-ledger-v4".equals(format) ? new String[]{"sessions", "operations", "transfers", "source_archives", "edit_history"} : "pachibo-ledger-v3".equals(format) ? new String[]{"sessions", "operations", "transfers", "source_archives"} : new String[]{"sessions", "operations", "transfers"};
                for (String table : tables) {
                    JSONArray data = input.getJSONArray(table);
                    for (int i = 0; i < data.length(); i++) {
                        JSONObject item = data.getJSONObject(i);
                        ContentValues v = new ContentValues();
                        java.util.Iterator<String> keys = item.keys();
                        while (keys.hasNext()) {
                            String key = keys.next(); Object value = item.get(key);
                            if (value == JSONObject.NULL) v.putNull(key);
                            else if (value instanceof Number) v.put(key, ((Number)value).longValue());
                            else v.put(key, value.toString());
                        }
                        // Exact repeats are harmless; differing content aborts the entire import.
                        insertOrMatch(db, table, "id", v);
                    }
                }
            } else {
                String payload = input.toString();
                String fingerprint = input.optString("source_sha256");
                if (fingerprint.isEmpty()) {
                    try {
                        byte[] hash = java.security.MessageDigest.getInstance("SHA-256").digest(payload.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        StringBuilder key = new StringBuilder();
                        for (byte b : hash) key.append(String.format("%02x", b & 255));
                        fingerprint = key.toString();
                    } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
                }
                try {
                    boolean archived;
                    try(Cursor c=db.rawQuery("SELECT 1 FROM source_archives WHERE id=? LIMIT 1",new String[]{fingerprint+"#0"})){
                        archived=c.moveToFirst();
                    }
                    if(!archived){
                        JSONArray chunks=SourceArchive.pack(fingerprint,payload);
                        for(int i=0;i<chunks.length();i++) {
                            JSONObject chunk=chunks.getJSONObject(i); ContentValues archive=new ContentValues();
                            archive.put("id",chunk.getString("id")); archive.put("payload",chunk.getString("payload"));
                            insertOrMatch(db,"source_archives","id",archive);
                        }
                    }
                } catch(JSONException e) { throw e; }
                catch(Exception e) { throw new IllegalStateException(e); }
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        return rows.length() + (input.optJSONArray("sessions") == null ? 0 : input.getJSONArray("sessions").length());
    }

    private static void insertOrMatch(SQLiteDatabase db, String table, String primaryKey, ContentValues incoming) {
        String id = incoming.getAsString(primaryKey);
        if (id == null || id.isEmpty()) throw new IllegalArgumentException("復元データのIDがありません");
        try (Cursor c = db.query(table, null, primaryKey + "=?", new String[]{id}, null, null, null)) {
            if (c.moveToFirst()) {
                for (String key : incoming.keySet()) {
                    int index = c.getColumnIndexOrThrow(key);
                    String old = c.isNull(index) ? null : c.getString(index);
                    if (!java.util.Objects.equals(old, incoming.getAsString(key)))
                        throw new IllegalStateException("既存データと競合しています。上書きせず取り込みを取り消しました: " + table + " / " + id);
                }
                return;
            }
        }
        db.insertOrThrow(table, null, incoming);
    }

    private static void insertOrClassifyPcbRecord(SQLiteDatabase db,ContentValues incoming) {
        String id=incoming.getAsString("id");
        try(Cursor c=db.query("records",null,"id=?",new String[]{id},null,null,null)){
            if(c.moveToFirst()){
                boolean inferred=("スロット".equals(incoming.getAsString("kind"))||"パチンコ".equals(incoming.getAsString("kind")))
                    &&"未分類".equals(c.getString(c.getColumnIndexOrThrow("kind")));
                if(inferred){
                    for(String key:incoming.keySet())if(!"kind".equals(key)){
                        int index=c.getColumnIndexOrThrow(key);String old=c.isNull(index)?null:c.getString(index);
                        if(!java.util.Objects.equals(old,incoming.getAsString(key))){inferred=false;break;}
                    }
                    if(inferred){
                        ContentValues update=new ContentValues();update.put("kind",incoming.getAsString("kind"));
                        db.update("records",update,"id=?",new String[]{id});return;
                    }
                }
            }
        }
        insertOrMatch(db,"records","id",incoming);
    }

    private static void importLegacyTimes(SQLiteDatabase db,JSONObject row) {
        Long start=legacyClock(row.optString("date"),row.optString("legacy_start"));
        Long end=legacyClock(row.optString("date"),row.optString("legacy_end"));
        if(start==null||end==null||end<start)return;
        String id=row.optString("id");
        JSONObject details;
        try(Cursor existing=db.rawQuery("SELECT payload FROM record_details WHERE id=?",new String[]{id})) {
            details=existing.moveToFirst()?new JSONObject(existing.getString(0)):new JSONObject();
        }catch(JSONException malformed){throw new IllegalStateException(malformed);}
        if(details.has("started_at")||details.has("ended_at"))return; // Preserve user-entered times.
        try {details.put("started_at",start).put("ended_at",end);}
        catch(JSONException impossible){throw new IllegalStateException(impossible);}
        ContentValues values=new ContentValues();values.put("id",id);values.put("payload",details.toString());
        db.insertWithOnConflict("record_details",null,values,SQLiteDatabase.CONFLICT_REPLACE);
    }

    private static Long legacyClock(String date,String raw) {
        try {
            if(!raw.matches("\\d{1,4}"))return null;
            int clock=Integer.parseInt(raw),hour=clock/100,minute=clock%100;
            if(hour>23||minute>59)return null;
            return java.time.LocalDate.parse(date).atTime(hour,minute)
                .atZone(java.time.ZoneId.of("Asia/Tokyo")).toInstant().toEpochMilli();
        }catch(Exception invalid){return null;}
    }

    void save(JSONObject row) {
        SQLiteDatabase db=getWritableDatabase();
        if(db.update("records",values(row),"id=?",new String[]{row.optString("id")})==0)db.insertOrThrow("records",null,values(row));
    }

    JSONObject recordDetails(String id) throws JSONException {
        try(Cursor c=getReadableDatabase().rawQuery("SELECT payload FROM record_details WHERE id=?",new String[]{id})){
            return c.moveToFirst()?new JSONObject(c.getString(0)):new JSONObject();
        }
    }
    java.util.Map<String,JSONObject> allRecordDetails() throws JSONException {
        java.util.Map<String,JSONObject> result=new java.util.HashMap<>();
        try(Cursor c=getReadableDatabase().rawQuery("SELECT id,payload FROM record_details",null)) {
            while(c.moveToNext())result.put(c.getString(0),new JSONObject(c.getString(1)));
        }
        return result;
    }
    void saveRecord(JSONObject record,JSONObject details) throws JSONException {
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();
        try{save(record);ContentValues v=new ContentValues();v.put("id",record.getString("id"));v.put("payload",details.toString());
            db.insertWithOnConflict("record_details",null,v,SQLiteDatabase.CONFLICT_REPLACE);db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }

    void delete(String id) { getWritableDatabase().delete("records", "id=?", new String[]{id}); }

    List<JSONObject> records() throws JSONException {
        List<JSONObject> result = new ArrayList<>();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT * FROM records ORDER BY date DESC, id DESC", null)) {
            while (c.moveToNext()) {
                JSONObject row = new JSONObject();
                for (String key : new String[]{"id", "date", "hall", "kind", "machine", "machine_number", "duration", "memo", "match_status", "source_item_id", "legacy_tag_bits"}) {
                    String value = c.getString(c.getColumnIndexOrThrow(key)); row.put(key, value == null ? JSONObject.NULL : value);
                }
                for (String key : new String[]{"investment_yen", "recovery_yen", "profit_yen"}) row.put(key, c.getLong(c.getColumnIndexOrThrow(key)));
                row.put("tag_ids", new JSONArray(c.getString(c.getColumnIndexOrThrow("tag_ids"))));
                result.add(row);
            }
        }
        return result;
    }

    JSONArray tags() throws JSONException {
        JSONArray result = new JSONArray();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT source_id,name,type,priority FROM tags ORDER BY name", null)) {
            while (c.moveToNext()) {
                JSONObject tag = new JSONObject();
                for (String key : new String[]{"source_id", "name", "type", "priority"}) {
                    String value = c.getString(c.getColumnIndexOrThrow(key)); tag.put(key, value == null ? JSONObject.NULL : value);
                }
                result.put(tag);
            }
        }
        return result;
    }

    String tagId(String name) {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT source_id FROM tags WHERE name=? LIMIT 1", new String[]{name})) {
            if (c.moveToFirst()) return c.getString(0);
        }
        String id = "local-" + UUID.randomUUID();
        ContentValues v = new ContentValues();
        v.put("source_id", id);
        v.put("name", name);
        v.put("type", "");
        v.put("priority", "");
        getWritableDatabase().insertOrThrow("tags", null, v);
        return id;
    }

    JSONObject backup() throws JSONException {
        SQLiteDatabase db = getReadableDatabase();
        db.beginTransaction();
        try {
        JSONObject out = new JSONObject();
        out.put("format", "pachibo-ledger-v7");
        out.put("tags", tags());
        JSONArray rows = new JSONArray();
        for (JSONObject row : records()) rows.put(row);
        out.put("records", rows);
        for (String table : new String[]{"sessions", "operations", "transfers", "source_archives", "edit_history", "accounts", "catalog", "record_details", "calendar_events"}) {
            JSONArray data = new JSONArray();
            try (Cursor c = db.rawQuery("SELECT * FROM " + table, null)) {
                while (c.moveToNext()) {
                    JSONObject item = new JSONObject();
                    for (int i = 0; i < c.getColumnCount(); i++) {
                        Object value = c.isNull(i) ? JSONObject.NULL : c.getType(i) == Cursor.FIELD_TYPE_INTEGER ? c.getLong(i) : c.getString(i);
                        item.put(c.getColumnName(i), value);
                    }
                    data.put(item);
                }
            }
            out.put(table, data);
        }
        db.setTransactionSuccessful();
        return out;
        } finally { db.endTransaction(); }
    }
}
