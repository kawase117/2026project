package jp.local.pachiboledger;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import java.util.*;
import java.time.LocalDate;
import org.json.JSONObject;

final class Catalog {
    static void createTables(SQLiteDatabase db){
        db.execSQL("CREATE TABLE catalog (id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('hall','machine')), name TEXT NOT NULL, UNIQUE(kind,name))");
        db.execSQL("CREATE TABLE record_details (id TEXT PRIMARY KEY NOT NULL REFERENCES records(id) ON DELETE CASCADE, payload TEXT NOT NULL)");
    }
    static void add(LedgerDb db,String kind,String name){
        name=name.trim(); if(name.isEmpty())return;
        ContentValues v=new ContentValues();v.put("id",kind+":"+name);v.put("kind",kind);v.put("name",name);
        db.getWritableDatabase().insertWithOnConflict("catalog",null,v,SQLiteDatabase.CONFLICT_IGNORE);
    }
    static List<String> names(LedgerDb db,String kind)throws Exception {return names(db,kind,null,null,false);}
    static List<String> names(LedgerDb db,String kind,String gameKind,String hall,boolean unclassified)throws Exception {
        if(!kind.equals("hall")&&!kind.equals("machine"))throw new IllegalArgumentException("一覧の種類が不正です");
        Set<String> names=new HashSet<>();
        Map<String,String> last=new HashMap<>();Map<String,Integer> recent=new HashMap<>();
        Map<String,Set<String>> machineKinds=new HashMap<>();
        Set<String> atHall=new HashSet<>();
        String cutoff=LocalDate.now().minusDays(90).toString();
        try(Cursor c=db.getReadableDatabase().rawQuery("SELECT name FROM catalog WHERE kind=?",new String[]{kind})){while(c.moveToNext())names.add(c.getString(0));}
        try(Cursor c=db.getReadableDatabase().rawQuery("SELECT date,hall,kind,machine FROM records",null)){
            while(c.moveToNext()){
                String name=kind.equals("hall")?c.getString(1):c.getString(3);
                if(name==null||name.isEmpty())continue;
                names.add(name);rank(name,c.getString(0),cutoff,last,recent);
                if(kind.equals("machine")){
                    String type=game(c.getString(2));if(type!=null)machineKinds.computeIfAbsent(name,k->new HashSet<>()).add(type);
                    if(hall!=null&&hall.equals(c.getString(1)))atHall.add(name);
                }
            }
        }
        for(JSONObject row:new SessionStore(db).sessions()){
            JSONObject meta=row.getJSONObject("metadata");String name=meta.optString(kind);
            if(name.isEmpty())continue;
            names.add(name);rank(name,row.optString("date"),cutoff,last,recent);
            if(kind.equals("machine")){
                String type=game(meta.optString("game_kind"));
                if(type==null)type="玉".equals(meta.optString("unit"))?"パチンコ":"スロット";
                machineKinds.computeIfAbsent(name,k->new HashSet<>()).add(type);
                if(hall!=null&&hall.equals(meta.optString("hall")))atHall.add(name);
            }
        }
        if(kind.equals("hall"))for(JSONObject account:new AccountStore(db).list())names.add(account.getString("hall"));
        names.remove("");
        if(kind.equals("machine")&&gameKind!=null){
            names.removeIf(name->{Set<String> types=machineKinds.get(name);
                return unclassified ? types!=null&&!types.isEmpty() : types==null||!types.contains(gameKind);
            });
        }
        List<String> sorted=new ArrayList<>(names);java.text.Collator collator=java.text.Collator.getInstance(Locale.JAPAN);
        sorted.sort((a,b)->{
            int fresh=Boolean.compare(last.getOrDefault(b,"").compareTo(cutoff)>=0,last.getOrDefault(a,"").compareTo(cutoff)>=0);
            if(fresh!=0)return fresh;
            int match=Boolean.compare(atHall.contains(b),atHall.contains(a));if(match!=0)return match;
            int date=last.getOrDefault(b,"").compareTo(last.getOrDefault(a,""));if(date!=0)return date;
            int count=Integer.compare(recent.getOrDefault(b,0),recent.getOrDefault(a,0));if(count!=0)return count;
            return collator.compare(a,b);
        });
        return sorted;
    }
    private static void rank(String name,String date,String cutoff,Map<String,String> last,Map<String,Integer> recent){
        if(date==null)return;
        if(date.compareTo(last.getOrDefault(name,""))>0)last.put(name,date);
        if(date.compareTo(cutoff)>=0)recent.put(name,recent.getOrDefault(name,0)+1);
    }
    private static String game(String value){
        if("スロット".equals(value)||"slot".equalsIgnoreCase(value))return "スロット";
        if("パチンコ".equals(value)||"pachinko".equalsIgnoreCase(value))return "パチンコ";
        return null;
    }
}
