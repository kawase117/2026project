package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Set;
import java.util.Enumeration;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Reads a complete backup before any database writes and checks its identity and structure. */
final class BackupIO {
    private static final long MAX_BYTES = 256L * 1024 * 1024;
    private BackupIO() {}

    static JSONObject readJson(InputStream input) throws Exception {
        byte[] bytes=read(input,MAX_BYTES);
        String value=new String(bytes,StandardCharsets.UTF_8);
        if(value.startsWith("\ufeff"))value=value.substring(1);
        JSONObject result=new JSONObject(value);
        validate(result);
        return result;
    }

    static JSONObject readZip(InputStream input,File cacheDir) throws Exception {
        File temporary=File.createTempFile("restore-",".zip",cacheDir);
        try{
            try(FileOutputStream output=new FileOutputStream(temporary)){
                byte[] buffer=new byte[16384];long size=0;int n;
                while((n=input.read(buffer))!=-1){
                    size+=n;if(size>MAX_BYTES)throw new IllegalArgumentException("ZIPがサイズ上限を超えています");
                    output.write(buffer,0,n);
                }
            }
            return readZipFile(temporary);
        }finally{if(!temporary.delete())temporary.deleteOnExit();}
    }

    private static JSONObject readZipFile(File file) throws Exception {
        byte[] backup=null;
        long total=0;
        int entries=0;
        try(ZipFile zip=new ZipFile(file,StandardCharsets.UTF_8)) {
            Enumeration<? extends ZipEntry> list=zip.entries();
            while(list.hasMoreElements()) {
                ZipEntry entry=list.nextElement();
                if(++entries>10000)throw new IllegalArgumentException("ZIP内のファイル数が多すぎます");
                ByteArrayOutputStream bytes="backup.json".equals(entry.getName())?new ByteArrayOutputStream():null;
                CRC32 crc=new CRC32();byte[] buffer=new byte[16384];int n;
                try(InputStream stream=zip.getInputStream(entry)){
                    while((n=stream.read(buffer))!=-1){
                        total+=n;
                        if(total>MAX_BYTES)throw new IllegalArgumentException("ZIPの展開サイズが上限を超えています");
                        crc.update(buffer,0,n);
                        if(bytes!=null)bytes.write(buffer,0,n);
                    }
                }
                if(entry.getCrc()!=-1&&crc.getValue()!=entry.getCrc())
                    throw new IllegalArgumentException("ZIP内のファイルが破損しています: "+entry.getName());
                if(bytes!=null){
                    if(backup!=null)throw new IllegalArgumentException("ZIP内にbackup.jsonが重複しています");
                    backup=bytes.toByteArray();
                }
            }
        }
        if(backup==null)throw new IllegalArgumentException("ZIP内にbackup.jsonがありません");
        return readJson(new java.io.ByteArrayInputStream(backup));
    }

    private static byte[] read(InputStream input,long limit) throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[16384];int n;
        while((n=input.read(buffer))!=-1){
            if((long)out.size()+n>limit)throw new IllegalArgumentException("バックアップがサイズ上限を超えています");
            out.write(buffer,0,n);
        }
        return out.toByteArray();
    }

    static void validate(JSONObject input) throws JSONException {
        String format=input.optString("format");
        int version;
        try{
            if(!format.startsWith("pachibo-ledger-v"))throw new NumberFormatException();
            version=Integer.parseInt(format.substring("pachibo-ledger-v".length()));
        }catch(NumberFormatException e){throw new JSONException("未対応のバックアップ形式です: "+format);}
        if(version<1||version>8)throw new JSONException("未対応のバックアップ形式です: "+format);
        checkTable(input,"records","id");
        if(input.has("tags"))checkTable(input,"tags","source_id");
        if(version>=2)for(String table:new String[]{"sessions","operations","transfers"})checkTable(input,table,"id");
        if(version>=3)checkTable(input,"source_archives","id");
        if(version>=4)checkTable(input,"edit_history","id");
        if(version>=5)checkTable(input,"accounts","id");
        if(version>=6)for(String table:new String[]{"catalog","record_details"})checkTable(input,table,"id");
        if(version>=7)checkTable(input,"calendar_events","id");
        if(version>=8)checkTable(input,"counters","id");
        checkDates(input.getJSONArray("records"),"records");
        if(version>=2)checkDates(input.getJSONArray("sessions"),"sessions");
    }

    private static void checkTable(JSONObject input,String name,String idKey)throws JSONException {
        JSONArray rows=input.getJSONArray(name);Set<String> ids=new HashSet<>();
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.getJSONObject(i);
            String id=row.optString(idKey,"");
            if(id.isEmpty())throw new JSONException(name+" の "+(i+1)+" 行目にIDがありません");
            if(!ids.add(id))throw new JSONException(name+" に重複IDがあります: "+id);
        }
    }

    private static void checkDates(JSONArray rows,String name)throws JSONException {
        for(int i=0;i<rows.length();i++){
            String value=rows.getJSONObject(i).optString("date","");
            try{LocalDate.parse(value);}catch(Exception e){throw new JSONException(name+" の "+(i+1)+" 行目の日付が不正です: "+value);}
        }
    }

    static String preview(JSONObject input)throws JSONException {
        int records=input.getJSONArray("records").length();
        JSONArray sessions=input.optJSONArray("sessions");
        int active=sessions==null?0:sessions.length();
        String first=null,last=null;
        for(String table:new String[]{"records","sessions"}){
            JSONArray rows=input.optJSONArray(table);if(rows==null)continue;
            for(int i=0;i<rows.length();i++){
                String date=rows.getJSONObject(i).getString("date");
                if(first==null||date.compareTo(first)<0)first=date;
                if(last==null||date.compareTo(last)>0)last=date;
            }
        }
        return "記録 "+(records+active)+"件（従来形式 "+records+"件・遊技セッション "+active+"件）\n"
            +"期間 "+(first==null?"記録なし":first+" ～ "+last)
            +"\nタグ "+length(input,"tags")+"件・イベント "+length(input,"calendar_events")+"件"
            +"\n交換率を含む口座設定 "+length(input,"accounts")+"件・計算条件 "+length(input,"record_details")+"件"
            +"\n既存の同一IDで内容が異なる場合は、全件を取り消します。";
    }

    private static int length(JSONObject data,String key){JSONArray rows=data.optJSONArray(key);return rows==null?0:rows.length();}
}
