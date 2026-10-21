package jp.local.pachiboledger;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.UUID;

/** Small-role counts are part of the ledger, including a one-step undo state. */
final class CounterStore {
    private final LedgerDb helper;
    CounterStore(LedgerDb helper){this.helper=helper;}
    static void createTable(SQLiteDatabase db){
        db.execSQL("CREATE TABLE counters (id TEXT PRIMARY KEY NOT NULL, owner_type TEXT NOT NULL CHECK(owner_type IN ('record','session')), owner_id TEXT NOT NULL, name TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0 CHECK(count>=0), undo_available INTEGER NOT NULL DEFAULT 0 CHECK(undo_available IN (0,1)), updated_at INTEGER NOT NULL)");
        db.execSQL("CREATE INDEX counters_owner ON counters(owner_type,owner_id)");
    }
    JSONArray list(String ownerType,String ownerId)throws JSONException{
        JSONArray out=new JSONArray();
        try(Cursor c=helper.getReadableDatabase().rawQuery("SELECT id,name,count,undo_available FROM counters WHERE owner_type=? AND owner_id=? ORDER BY updated_at,id",new String[]{ownerType,ownerId})){
            while(c.moveToNext())out.put(new JSONObject().put("id",c.getString(0)).put("name",c.getString(1))
                .put("count",c.getLong(2)).put("undo_available",c.getInt(3)==1));
        }
        return out;
    }
    void add(String ownerType,String ownerId,String name){
        name=name.trim();
        if(name.isEmpty())throw new IllegalArgumentException("カウント項目の名前を入力してください");
        if(!"record".equals(ownerType)&&!"session".equals(ownerType))throw new IllegalArgumentException("記録の種類が不正です");
        SQLiteDatabase db=helper.getWritableDatabase();
        String table="record".equals(ownerType)?"records":"sessions";
        try(Cursor c=db.rawQuery("SELECT 1 FROM "+table+" WHERE id=?",new String[]{ownerId})){
            if(!c.moveToFirst())throw new IllegalArgumentException("先に遊技記録を保存してください");
        }
        ContentValues v=new ContentValues();v.put("id",UUID.randomUUID().toString());v.put("owner_type",ownerType);
        v.put("owner_id",ownerId);v.put("name",name);v.put("count",0);v.put("undo_available",0);
        v.put("updated_at",System.currentTimeMillis());db.insertOrThrow("counters",null,v);
    }
    void increment(String id){
        SQLiteDatabase db=helper.getWritableDatabase();
        db.execSQL("UPDATE counters SET count=count+1,undo_available=1,updated_at=? WHERE id=?",new Object[]{System.currentTimeMillis(),id});
        if(android.database.DatabaseUtils.longForQuery(db,"SELECT changes()",null)==0)throw new IllegalArgumentException("項目が見つかりません");
    }
    void undo(String id){
        SQLiteDatabase db=helper.getWritableDatabase();
        db.execSQL("UPDATE counters SET count=count-1,undo_available=0,updated_at=? WHERE id=? AND undo_available=1 AND count>0",new Object[]{System.currentTimeMillis(),id});
        if(android.database.DatabaseUtils.longForQuery(db,"SELECT changes()",null)==0)throw new IllegalArgumentException("取り消せる直前の加算はありません");
    }
}
