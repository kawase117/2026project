package jp.local.pachiboledger;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.JSONObject;
import org.json.JSONException;
import java.util.*;

/** Reusable input defaults. Existing operations always retain their own valuation rate. */
final class AccountStore {
    private final LedgerDb helper;
    AccountStore(LedgerDb helper) { this.helper=helper; }

    static void createTables(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE accounts (id TEXT PRIMARY KEY NOT NULL, hall TEXT NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL CHECK(unit IN ('玉','枚')), rate_yen INTEGER, rate_units INTEGER, UNIQUE(hall,name,unit), CHECK((rate_yen IS NULL AND rate_units IS NULL) OR (rate_yen IS NOT NULL AND rate_units IS NOT NULL AND rate_yen>0 AND rate_units>0)))");
    }

    List<JSONObject> list() throws JSONException {
        List<JSONObject> rows=new ArrayList<>();
        try(Cursor c=helper.getReadableDatabase().rawQuery("SELECT * FROM accounts ORDER BY hall,name,unit,id",null)) {
            while(c.moveToNext()) {
                JSONObject row=new JSONObject();
                for(int i=0;i<c.getColumnCount();i++) row.put(c.getColumnName(i),c.isNull(i) ? JSONObject.NULL
                    : c.getType(i)==Cursor.FIELD_TYPE_INTEGER ? c.getLong(i) : c.getString(i));
                rows.add(row);
            }
        }
        return rows;
    }
    JSONObject forHall(String hall,String gameKind) throws JSONException {
        String unit="パチンコ".equals(gameKind)?"玉":"枚";
        JSONObject fallback=null,configured=null;
        for(JSONObject row:list())if(hall.equals(row.optString("hall"))&&unit.equals(row.optString("unit"))){
            if(gameKind.equals(row.optString("name"))&&!row.isNull("rate_yen"))return row;
            if(!row.isNull("rate_yen")&&configured==null)configured=row;
            if(fallback==null)fallback=row;
        }
        if(configured!=null)return configured;
        if(fallback!=null)return fallback;
        String id="account-"+UUID.randomUUID();
        save(id,null,hall,gameKind,unit,null,null);
        for(JSONObject row:list())if(id.equals(row.optString("id")))return row;
        throw new IllegalStateException("ホールを登録できませんでした");
    }

    void save(String id,JSONObject expected,String hall,String name,String unit,Long yen,Long units) throws JSONException {
        hall=hall.trim(); name=name.trim();
        if(id==null || id.isEmpty() || hall.isEmpty() || name.isEmpty()) throw new IllegalArgumentException("ホールと口座名を入力してください");
        if(!"玉".equals(unit) && !"枚".equals(unit)) throw new IllegalArgumentException("単位を選択してください");
        if((yen==null)!=(units==null) || (yen!=null && (yen<=0 || units<=0))) throw new IllegalArgumentException("評価率は円と数量の両方を正の整数で入力してください");
        SQLiteDatabase db=helper.getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject current=null;
            for(JSONObject row:list()) if(id.equals(row.getString("id"))) current=row;
            if((current==null)!=(expected==null)) throw new IllegalStateException("口座が更新されています。開き直してください");
            if(current!=null) for(Iterator<String> it=current.keys();it.hasNext();) {
                String key=it.next();
                if(!expected.has(key) || current.isNull(key)!=expected.isNull(key) || !current.get(key).toString().equals(expected.get(key).toString()))
                    throw new IllegalStateException("口座が更新されています。開き直してください");
            }
            ContentValues v=new ContentValues(); v.put("id",id); v.put("hall",hall); v.put("name",name); v.put("unit",unit);
            v.put("rate_yen",yen); v.put("rate_units",units);
            if(current==null) db.insertOrThrow("accounts",null,v); else db.update("accounts",v,"id=?",new String[]{id});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    static JSONObject snapshot(JSONObject account,JSONObject metadata) throws JSONException {
        JSONObject copy=new JSONObject(metadata.toString());
        copy.put("hall",account.getString("hall")).put("account_name",account.getString("name")).put("unit",account.getString("unit"));
        copy.put("default_rate_yen",account.get("rate_yen")).put("default_rate_units",account.get("rate_units"));
        return copy;
    }
}
