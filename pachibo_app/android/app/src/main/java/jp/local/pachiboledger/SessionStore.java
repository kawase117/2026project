package jp.local.pachiboledger;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.JSONObject;
import org.json.JSONException;
import java.time.LocalDate;
import java.util.*;

/** Persistence for new sessions; legacy imported amounts remain in records. */
final class SessionStore {
    private final LedgerDb helper;
    SessionStore(LedgerDb helper) { this.helper = helper; }

    static void createTables(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE sessions (id TEXT PRIMARY KEY NOT NULL, date TEXT NOT NULL, account TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','ended')), metadata TEXT NOT NULL, started_at INTEGER NOT NULL, ended_at INTEGER)");
        db.execSQL("CREATE UNIQUE INDEX one_active_session ON sessions(state) WHERE state='active'");
        db.execSQL("CREATE INDEX sessions_date ON sessions(date)");
        db.execSQL("CREATE TABLE operations (id TEXT PRIMARY KEY NOT NULL, session_id TEXT NOT NULL REFERENCES sessions(id), kind TEXT NOT NULL CHECK(kind IN ('cash','quantity')), delta INTEGER NOT NULL, rate_yen INTEGER, rate_units INTEGER, created_at INTEGER NOT NULL, CHECK((rate_yen IS NULL AND rate_units IS NULL) OR (rate_yen IS NOT NULL AND rate_units IS NOT NULL AND rate_yen>0 AND rate_units>0)))");
        db.execSQL("CREATE TABLE transfers (id TEXT PRIMARY KEY NOT NULL, from_id TEXT NOT NULL REFERENCES sessions(id), to_id TEXT NOT NULL REFERENCES sessions(id), quantity INTEGER CHECK(quantity>=0), rate_yen INTEGER, rate_units INTEGER, CHECK(from_id<>to_id), CHECK((rate_yen IS NULL AND rate_units IS NULL) OR (rate_yen IS NOT NULL AND rate_units IS NOT NULL AND rate_yen>0 AND rate_units>0)))");
    }

    static void createHistory(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE edit_history (id TEXT PRIMARY KEY NOT NULL, entity_type TEXT NOT NULL CHECK(entity_type IN ('operations','transfers')), entity_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at INTEGER NOT NULL, reverted_edit_id TEXT, UNIQUE(entity_type,entity_id,revision))");
    }

    List<JSONObject> history(String sessionId) throws JSONException {
        List<JSONObject> rows=new ArrayList<>();
        String sql="SELECT h.* FROM edit_history h WHERE (entity_type='operations' AND entity_id IN (SELECT id FROM operations WHERE session_id=?)) OR (entity_type='transfers' AND entity_id IN (SELECT id FROM transfers WHERE from_id=? OR to_id=?)) ORDER BY created_at DESC,rowid DESC";
        try(Cursor c=helper.getReadableDatabase().rawQuery(sql,new String[]{sessionId,sessionId,sessionId})) {
            while(c.moveToNext()) rows.add(detailRow(c));
        }
        return rows;
    }

    void undo(String historyId) throws JSONException {
        SQLiteDatabase db=helper.getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject edit;
            try(Cursor c=db.rawQuery("SELECT * FROM edit_history WHERE id=?",new String[]{historyId})) {
                if(!c.moveToFirst()) throw new IllegalStateException("訂正履歴がありません");
                edit=detailRow(c);
            }
            String table=edit.getString("entity_type"), entity=edit.getString("entity_id");
            try(Cursor c=db.rawQuery("SELECT id FROM edit_history WHERE entity_type=? AND entity_id=? ORDER BY revision DESC LIMIT 1",new String[]{table,entity})) {
                if(!c.moveToFirst() || !historyId.equals(c.getString(0)))
                    throw new IllegalStateException("この明細には後の変更があります。最新の変更から戻してください");
            }
            JSONObject before=new JSONObject(edit.getString("before_json"));
            boolean transfer="transfers".equals(table);
            String amountKey=transfer ? "quantity" : "delta";
            correct(new JSONObject(edit.getString("after_json")),transfer,
                before.isNull(amountKey) ? null : before.getLong(amountKey),
                before.isNull("rate_yen") ? null : before.getLong("rate_yen"),
                before.isNull("rate_units") ? null : before.getLong("rate_units"),historyId);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    void start(String id, String date, String account, JSONObject metadata) {
        SQLiteDatabase db = helper.getWritableDatabase();
        insertSession(db, id, date, account, metadata);
    }

    JSONObject session(String id) throws JSONException {
        try(Cursor c=helper.getReadableDatabase().rawQuery("SELECT * FROM sessions WHERE id=?",new String[]{id})){
            if(!c.moveToFirst())throw new IllegalArgumentException("記録がありません");
            JSONObject row=detailRow(c);row.put("metadata",new JSONObject(row.getString("metadata")));return row;
        }
    }
    void deleteSession(String id) {
        SQLiteDatabase db=helper.getWritableDatabase(); db.beginTransaction();
        try {
            try(Cursor c=db.rawQuery("SELECT 1 FROM sessions WHERE id=?",new String[]{id})) {
                if(!c.moveToFirst())throw new IllegalArgumentException("記録がありません");
            }
            try(Cursor c=db.rawQuery("SELECT 1 FROM transfers WHERE from_id=? OR to_id=? LIMIT 1",new String[]{id,id})) {
                if(c.moveToFirst())throw new IllegalStateException("台移動でつながる記録は削除できません。明細を確認してください");
            }
            db.execSQL("DELETE FROM edit_history WHERE entity_type='operations' AND entity_id IN (SELECT id FROM operations WHERE session_id=?)",new Object[]{id});
            db.delete("operations","session_id=?",new String[]{id});
            db.delete("sessions","id=?",new String[]{id});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    private void times(String id,long start,Long end) throws JSONException {
        JSONObject row=session(id);boolean ended="ended".equals(row.getString("state"));
        if(ended!=(end!=null) || (end!=null && end<start))throw new IllegalArgumentException("開始・終了日時を確認してください");
        ContentValues v=new ContentValues();v.put("started_at",start);v.put("ended_at",end);
        helper.getWritableDatabase().update("sessions",v,"id=?",new String[]{id});
    }
    void startAt(String id,String date,String account,JSONObject meta,long at)throws JSONException{
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try{start(id,date,account,meta);times(id,at,null);db.setTransactionSuccessful();}finally{db.endTransaction();}
    }
    void finishAt(String id,String operation,Long cash,Long quantity,Long yen,Long units,long at)throws JSONException{
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try{long start=session(id).getLong("started_at");if(at<start)throw new IllegalArgumentException("終了日時は開始日時以降にしてください");
            finish(id,operation,cash,quantity,yen,units);times(id,start,at);db.setTransactionSuccessful();}finally{db.endTransaction();}
    }
    void finishWithAmountsAt(String id,String operation,long cashInvestment,long quantityInvestment,
                             long cashRecovery,long quantityRecovery,Long yen,Long units,
                             String memo,org.json.JSONArray tags,long at)throws JSONException{
        if(cashInvestment<0||quantityInvestment<0||cashRecovery<0||quantityRecovery<0)
            throw new IllegalArgumentException("投資・回収は0以上で入力してください");
        validateRate(yen,units);
        if((quantityInvestment>0||quantityRecovery>0) && yen==null)
            throw new IllegalArgumentException("玉・メダルを入力した場合は交換率を登録してください");
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try{
            requireActive(db,id);
            JSONObject current=session(id);
            long start=current.getLong("started_at");
            if(at<start||!java.time.Instant.ofEpochMilli(at).atZone(java.time.ZoneId.systemDefault())
                .toLocalDate().toString().equals(current.getString("date")))
                throw new IllegalArgumentException("終了時刻は開始以降の同じ遊技日を指定してください");
            if(cashInvestment>0)insertOperation(db,operation+":investment-cash",id,true,-cashInvestment,null,null);
            if(quantityInvestment>0)insertOperation(db,operation+":investment-quantity",id,false,-quantityInvestment,yen,units);
            insertOperation(db,operation+":recovery-cash",id,true,cashRecovery,null,null);
            insertOperation(db,operation+":recovery-quantity",id,false,quantityRecovery,yen,units);
            JSONObject metadata=current.getJSONObject("metadata");
            metadata.put("memo",memo).put("tag_ids",tags);
            saveMetadata(id,metadata);
            end(db,id);times(id,start,at);
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    void updateActiveEdited(String id,JSONObject expected,JSONObject account,String hall,String machine,String number,
                            String memo,org.json.JSONArray tags,long start)throws JSONException {
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try {
            requireActive(db,id);
            editBasicsTimed(id,expected,hall,machine,number,memo,start,null);
            setActiveAccount(id,account,tags);
            db.setTransactionSuccessful();
        } finally {db.endTransaction();}
    }
    private void setActiveAccount(String id,JSONObject account,org.json.JSONArray tags)throws JSONException {
        SQLiteDatabase db=helper.getWritableDatabase();
        ContentValues row=new ContentValues();row.put("account",account.getString("id"));
        db.update("sessions",row,"id=?",new String[]{id});
        JSONObject current=metadata(id);
        current.put("account_name",account.getString("name")).put("unit",account.getString("unit"))
            .put("default_rate_yen",account.get("rate_yen")).put("default_rate_units",account.get("rate_units"))
            .put("tag_ids",tags);
        saveMetadata(id,current);
    }
    void completeEdited(String id,JSONObject expected,JSONObject account,String hall,String machine,String number,String gameKind,
                        String memo,org.json.JSONArray tags,long start,long end,String operation,
                        long cashInvestment,long quantityInvestment,long cashRecovery,long quantityRecovery,
                        Long yen,Long units)throws JSONException {
        if(!gameKind.equals(expected.optString("game_kind")))
            throw new IllegalArgumentException("開始後の遊技種別変更はできません");
        SQLiteDatabase db=helper.getWritableDatabase(); db.beginTransaction();
        try {
            editBasicsTimed(id,expected,hall,machine,number,memo,start,null);
            setActiveAccount(id,account,tags);
            finishWithAmountsAt(id,operation,cashInvestment,quantityInvestment,cashRecovery,quantityRecovery,
                yen,units,memo,tags,end);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    void reviseCompleted(String id,JSONObject expected,JSONObject account,String hall,String machine,String number,
                         String memo,org.json.JSONArray tags,long start,long end,
                         long cashIn,long quantityIn,long cashOut,long quantityOut,Long yen,Long units)throws JSONException {
        if(cashIn<0||quantityIn<0||cashOut<0||quantityOut<0)throw new IllegalArgumentException("投資・回収は0以上で入力してください");
        if(end<start)throw new IllegalArgumentException("終了時刻は開始時刻以降にしてください");
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try{
            JSONObject current=session(id);
            if(!"ended".equals(current.getString("state")))throw new IllegalStateException("終了済みの記録ではありません");
            try(Cursor c=db.rawQuery("SELECT 1 FROM transfers WHERE from_id=? OR to_id=? LIMIT 1",new String[]{id,id})){
                if(c.moveToFirst())throw new IllegalStateException("台移動を含む記録は明細から訂正してください");
            }
            String date=current.getString("date");
            java.time.ZoneId zone=java.time.ZoneId.systemDefault();
            if(!java.time.Instant.ofEpochMilli(start).atZone(zone).toLocalDate().toString().equals(date)
                ||!java.time.Instant.ofEpochMilli(end).atZone(zone).toLocalDate().toString().equals(date))
                throw new IllegalArgumentException("開始・終了は同じ遊技日を指定してください");
            editBasicsTimed(id,expected,hall,machine,number,memo,start,end);
            setActiveAccount(id,account,tags);
            reviseAmount(db,id,true,true,cashIn,null,null);
            reviseAmount(db,id,false,true,quantityIn,yen,units);
            reviseAmount(db,id,true,false,cashOut,null,null);
            reviseAmount(db,id,false,false,quantityOut,yen,units);
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    private void reviseAmount(SQLiteDatabase db,String id,boolean cash,boolean investment,long desired,Long yen,Long units)throws JSONException{
        List<JSONObject> matching=new ArrayList<>();long observed=0;
        for(JSONObject row:details(id,false)){
            if(cash!="cash".equals(row.getString("kind")))continue;
            long delta=row.getLong("delta");
            if(investment!=(delta<0))continue;
            if(investment)observed=Math.addExact(observed,Math.negateExact(delta));
            else observed=Math.addExact(observed,delta);
            matching.add(row);
        }
        if(observed==desired)return;
        if(!cash&&desired>0&&yen==null)throw new IllegalArgumentException("玉・メダルを訂正するにはホールの交換率が必要です");
        long signed=investment?-desired:desired;
        if(matching.isEmpty())insertOperation(db,UUID.randomUUID().toString(),id,cash,signed,cash?null:yen,cash?null:units);
        else{
            boolean first=true;
            for(JSONObject row:matching){
                long target=first?signed:0;first=false;
                Long rateYen=cash?null:target==0&&row.isNull("rate_yen")?null:yen;
                Long rateUnits=cash?null:target==0&&row.isNull("rate_units")?null:units;
                if(target!=row.getLong("delta") || (!cash&&target!=0))correct(row,false,target,rateYen,rateUnits);
            }
        }
    }
    void moveAt(String id,String next,String transfer,Long quantity,Long yen,Long units,JSONObject meta,long at)throws JSONException{
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try{long start=session(id).getLong("started_at");if(at<start)throw new IllegalArgumentException("移動日時は開始日時以降にしてください");
            move(id,next,transfer,quantity,yen,units,meta);times(id,start,at);times(next,at,null);db.setTransactionSuccessful();}finally{db.endTransaction();}
    }
    void editBasicsTimed(String id,JSONObject expected,String hall,String machine,String number,String memo,long start,Long end)throws JSONException{
        SQLiteDatabase db=helper.getWritableDatabase();db.beginTransaction();
        try{editBasics(id,expected,hall,machine,number,memo);times(id,start,end);db.setTransactionSuccessful();}finally{db.endTransaction();}
    }

    private static void insertSession(SQLiteDatabase db, String id, String date, String account, JSONObject metadata) {
        require(id); require(account); Objects.requireNonNull(metadata); LocalDate.parse(date);
        ContentValues row = new ContentValues();
        row.put("id", id); row.put("date", date); row.put("account", account);
        row.put("state", "active"); row.put("metadata", metadata.toString());
        row.put("started_at", System.currentTimeMillis());
        db.insertOrThrow("sessions", null, row);
    }

    void saveMetadata(String id, JSONObject metadata) {
        ContentValues row = new ContentValues(); row.put("metadata", metadata.toString());
        if (helper.getWritableDatabase().update("sessions", row, "id=?", new String[]{id}) != 1)
            throw new IllegalArgumentException("記録がありません");
    }

    JSONObject metadata(String id) throws JSONException {
        try(Cursor c=helper.getReadableDatabase().rawQuery("SELECT metadata FROM sessions WHERE id=?",new String[]{id})) {
            if(!c.moveToFirst()) throw new IllegalArgumentException("記録がありません");
            return new JSONObject(c.getString(0));
        }
    }

    /** Merge only the field being edited, retaining tags, defaults and other concurrent fields. */
    void patchMetadata(String id,JSONObject patch) throws JSONException {
        SQLiteDatabase db=helper.getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject current=metadata(id);
            for(Iterator<String> it=patch.keys();it.hasNext();) { String key=it.next(); current.put(key,patch.get(key)); }
            saveMetadata(id,current); db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    void editBasics(String id,JSONObject expected,String hall,String machine,String number,String memo) throws JSONException {
        hall=hall.trim();
        if(hall.isEmpty()) throw new IllegalArgumentException("ホールを入力してください");
        SQLiteDatabase db=helper.getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject current=metadata(id);
            for(String key:new String[]{"hall","machine","number","memo"})
                if(!current.optString(key).equals(expected.optString(key))) throw new IllegalStateException("記録が更新されています。開き直してください");
            // A transfer chain belongs to one hall. A spelling correction must stay consistent at both ends.
            Set<String> connected=new HashSet<>(); connected.add(id);
            List<String[]> edges=new ArrayList<>();
            try(Cursor c=db.rawQuery("SELECT from_id,to_id FROM transfers",null)) { while(c.moveToNext()) edges.add(new String[]{c.getString(0),c.getString(1)}); }
            boolean changed;
            do { changed=false; for(String[] edge:edges) if(connected.contains(edge[0]) || connected.contains(edge[1])) {
                changed|=connected.add(edge[0]); changed|=connected.add(edge[1]);
            }} while(changed);
            if(!hall.equals(current.optString("hall"))) for(String linked:connected) patchMetadata(linked,new JSONObject().put("hall",hall));
            patchMetadata(id,new JSONObject().put("machine",machine.trim()).put("number",number.trim()).put("memo",memo));
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    void add(String operationId, String sessionId, boolean cash, long delta, Long rateYen, Long rateUnits) {
        SQLiteDatabase db = helper.getWritableDatabase();
        db.beginTransaction();
        try {
            requireActive(db, sessionId);
            insertOperation(db, operationId, sessionId, cash, delta, rateYen, rateUnits);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    private static void insertOperation(SQLiteDatabase db, String id, String sessionId, boolean cash,
                                        long delta, Long yen, Long units) {
        require(id); validateRate(yen, units);
        ContentValues row = new ContentValues();
        row.put("id", id); row.put("session_id", sessionId); row.put("kind", cash ? "cash" : "quantity");
        row.put("delta", delta); row.put("rate_yen", yen); row.put("rate_units", units);
        row.put("created_at", System.currentTimeMillis());
        db.insertOrThrow("operations", null, row);
    }

    /** Explicit zero recovery is accepted; an absent recovery is not silently converted to zero. */
    void finish(String id, String operationId, Long cashRecovery, Long deposit, Long yen, Long units) {
        if (cashRecovery == null || deposit == null || cashRecovery < 0 || deposit < 0)
            throw new IllegalArgumentException("回収と貯玉数量を確認してください");
        SQLiteDatabase db = helper.getWritableDatabase();
        db.beginTransaction();
        try {
            requireActive(db, id);
            insertOperation(db, operationId + ":cash", id, true, cashRecovery, null, null);
            insertOperation(db, operationId + ":deposit", id, false, deposit, yen, units);
            end(db, id);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    void move(String id, String nextId, String transferId, Long quantity, Long yen, Long units, JSONObject nextMetadata) {
        require(transferId); validateRate(yen, units);
        if (quantity != null && quantity < 0) throw new IllegalArgumentException("数量は0以上です");
        SQLiteDatabase db = helper.getWritableDatabase();
        db.beginTransaction();
        try {
            requireActive(db, id);
            String date, account;
            try (Cursor c = db.rawQuery("SELECT date,account FROM sessions WHERE id=?", new String[]{id})) {
                if (!c.moveToFirst()) throw new IllegalArgumentException("記録がありません");
                date = c.getString(0); account = c.getString(1);
            }
            end(db, id);
            insertSession(db, nextId, date, account, nextMetadata);
            ContentValues row = new ContentValues();
            row.put("id", transferId); row.put("from_id", id); row.put("to_id", nextId);
            row.put("quantity", quantity); row.put("rate_yen", yen); row.put("rate_units", units);
            db.insertOrThrow("transfers", null, row);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    List<JSONObject> sessions() throws JSONException {
        List<JSONObject> rows = new ArrayList<>();
        try (Cursor c = helper.getReadableDatabase().rawQuery("SELECT * FROM sessions ORDER BY started_at DESC,id", null)) {
            while (c.moveToNext()) {
                JSONObject row = new JSONObject();
                for (String key : new String[]{"id", "date", "account", "state"})
                    row.put(key, c.getString(c.getColumnIndexOrThrow(key)));
                row.put("metadata", new JSONObject(c.getString(c.getColumnIndexOrThrow("metadata"))));
                row.put("started_at", c.getLong(c.getColumnIndexOrThrow("started_at")));
                int end = c.getColumnIndexOrThrow("ended_at");
                row.put("ended_at", c.isNull(end) ? JSONObject.NULL : c.getLong(end));
                rows.add(row);
            }
        }
        return rows;
    }

    Accounting.Result calculate(Set<String> selected) {
        return snapshot().calculate(selected);
    }

    /** A detached row is also the optimistic concurrency token for a correction. */
    List<JSONObject> details(String sessionId, boolean transfer) throws JSONException {
        List<JSONObject> rows = new ArrayList<>();
        String sql = transfer ? "SELECT * FROM transfers WHERE from_id=? OR to_id=? ORDER BY id"
            : "SELECT * FROM operations WHERE session_id=? ORDER BY created_at,id";
        try (Cursor c = helper.getReadableDatabase().rawQuery(sql,
                transfer ? new String[]{sessionId,sessionId} : new String[]{sessionId})) {
            while (c.moveToNext()) rows.add(detailRow(c));
        }
        return rows;
    }

    private static JSONObject detailRow(Cursor c) throws JSONException {
        JSONObject row = new JSONObject();
        for (int i=0; i<c.getColumnCount(); i++)
            row.put(c.getColumnName(i), c.isNull(i) ? JSONObject.NULL
                : c.getType(i)==Cursor.FIELD_TYPE_INTEGER ? c.getLong(i) : c.getString(i));
        return row;
    }

    /** Keeps identities, endpoints, kind and timestamps unchanged. Both transfer ends share this row. */
    void correct(JSONObject expected, boolean transfer, Long amount, Long yen, Long units) throws JSONException {
        correct(expected,transfer,amount,yen,units,null);
    }

    private void correct(JSONObject expected, boolean transfer, Long amount, Long yen, Long units, String revertedId) throws JSONException {
        validateRate(yen,units);
        if (transfer && amount!=null && amount<0) throw new IllegalArgumentException("数量は0以上です");
        if (!transfer && amount==null) throw new IllegalArgumentException("金額・数量が必要です");
        SQLiteDatabase db = helper.getWritableDatabase();
        String table=transfer ? "transfers" : "operations", id=expected.getString("id");
        db.beginTransaction();
        try {
            JSONObject current;
            try(Cursor c=db.rawQuery("SELECT * FROM "+table+" WHERE id=?",new String[]{id})) {
                if(!c.moveToFirst()) throw new IllegalStateException("明細がありません");
                current=detailRow(c);
            }
            Iterator<String> keys=current.keys();
            while(keys.hasNext()) {
                String key=keys.next();
                if(!expected.has(key) || current.isNull(key)!=expected.isNull(key)
                    || !current.get(key).toString().equals(expected.get(key).toString()))
                    throw new IllegalStateException("明細が更新されています。開き直して訂正してください");
            }
            if(!transfer && "cash".equals(current.getString("kind")) && yen!=null)
                throw new IllegalArgumentException("現金明細に評価率は設定できません");
            ContentValues values=new ContentValues();
            values.put(transfer ? "quantity" : "delta",amount);
            values.put("rate_yen",yen); values.put("rate_units",units);
            if(db.update(table,values,"id=?",new String[]{id})!=1) throw new IllegalStateException("訂正できませんでした");
            JSONObject after=new JSONObject(current.toString());
            for(String key:values.keySet()) after.put(key,values.get(key)==null ? JSONObject.NULL : values.get(key));
            long revision;
            try(Cursor c=db.rawQuery("SELECT COALESCE(MAX(revision),0)+1 FROM edit_history WHERE entity_type=? AND entity_id=?",new String[]{table,id})) {
                c.moveToFirst(); revision=c.getLong(0);
            }
            ContentValues history=new ContentValues();
            history.put("id",UUID.randomUUID().toString()); history.put("entity_type",table); history.put("entity_id",id);
            history.put("revision",revision); history.put("before_json",current.toString()); history.put("after_json",after.toString());
            history.put("created_at",System.currentTimeMillis()); history.put("reverted_edit_id",revertedId);
            db.insertOrThrow("edit_history",null,history);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    static final class Snapshot {
        private final List<Accounting.Entry> entries;
        private final List<Accounting.Transfer> transfers;
        Snapshot(List<Accounting.Entry> entries, List<Accounting.Transfer> transfers) {
            this.entries = entries; this.transfers = transfers;
        }
        Accounting.Result calculate(Set<String> selected) { return Accounting.calculate(entries, transfers, selected); }
    }

    Snapshot snapshot() {
        SQLiteDatabase db = helper.getReadableDatabase();
        List<Accounting.Entry> entries = new ArrayList<>();
        List<Accounting.Transfer> transfers = new ArrayList<>();
        db.beginTransaction();
        try {
            try (Cursor c = db.rawQuery("SELECT id,session_id,kind,delta,rate_yen,rate_units FROM operations", null)) {
                while (c.moveToNext()) entries.add("cash".equals(c.getString(2))
                    ? Accounting.Entry.cash(c.getString(0), c.getString(1), c.getLong(3))
                    : Accounting.Entry.quantity(c.getString(0), c.getString(1), c.getLong(3), rate(c, 4)));
            }
            try (Cursor c = db.rawQuery("SELECT id,from_id,to_id,quantity,rate_yen,rate_units FROM transfers", null)) {
                while (c.moveToNext()) transfers.add(new Accounting.Transfer(c.getString(0), c.getString(1),
                    c.getString(2), c.isNull(3) ? null : c.getLong(3), rate(c, 4)));
            }
            Snapshot result = new Snapshot(entries, transfers);
            db.setTransactionSuccessful();
            return result;
        } finally { db.endTransaction(); }
    }

    private static Accounting.Rate rate(Cursor c, int i) {
        return c.isNull(i) ? null : new Accounting.Rate(c.getLong(i), c.getLong(i + 1));
    }
    private static void requireActive(SQLiteDatabase db, String id) {
        try (Cursor c = db.rawQuery("SELECT state FROM sessions WHERE id=?", new String[]{id})) {
            if (!c.moveToFirst() || !"active".equals(c.getString(0))) throw new IllegalStateException("遊技中の記録ではありません");
        }
    }
    private static void end(SQLiteDatabase db, String id) {
        ContentValues row = new ContentValues(); row.put("state", "ended"); row.put("ended_at", System.currentTimeMillis());
        if (db.update("sessions", row, "id=? AND state='active'", new String[]{id}) != 1)
            throw new IllegalStateException("終了できませんでした");
    }
    private static void require(String value) {
        if (value == null || value.trim().isEmpty()) throw new IllegalArgumentException("ID・口座が必要です");
    }
    private static void validateRate(Long yen, Long units) {
        if ((yen == null) != (units == null) || (yen != null && (yen <= 0 || units <= 0)))
            throw new IllegalArgumentException("換算率が不正です");
    }
}
