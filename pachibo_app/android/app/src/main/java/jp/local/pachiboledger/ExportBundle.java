package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** A consistent backup snapshot rendered as lossless CSV tables plus restorable JSON. */
final class ExportBundle {
    private ExportBundle() {}
    static String csv(JSONArray rows, String... initialColumns) throws Exception {
        Set<String> columns = new LinkedHashSet<>(Arrays.asList(initialColumns));
        for (int i=0;i<rows.length();i++) {
            Iterator<String> keys=rows.getJSONObject(i).keys(); while(keys.hasNext()) columns.add(keys.next());
        }
        StringBuilder result=new StringBuilder("\ufeff");
        List<String> header=new ArrayList<>(columns); header.add("__null_fields"); append(result,header);
        for(int i=0;i<rows.length();i++) {
            JSONObject row=rows.getJSONObject(i); List<String> values=new ArrayList<>(); JSONArray nulls=new JSONArray();
            for(String key:columns) {
                if(!row.has(key)||row.isNull(key)) { values.add(""); nulls.put(key); }
                else values.add(row.get(key).toString());
            }
            values.add(nulls.toString()); append(result,values);
        }
        return result.toString();
    }
    private static void append(StringBuilder result, List<String> cells) {
        for(int i=0;i<cells.size();i++) {
            if(i>0) result.append(','); result.append('"').append(cells.get(i).replace("\"","\"\"")).append('"');
        }
        result.append("\r\n");
    }
    private static void write(ZipOutputStream zip,String path,byte[] value) throws Exception {
        zip.putNextEntry(new ZipEntry(path)); zip.write(value); zip.closeEntry();
    }
    private static void text(ZipOutputStream zip,String path,String value) throws Exception { write(zip,path,value.getBytes(StandardCharsets.UTF_8)); }
    static void write(JSONObject backup, OutputStream output) throws Exception {
        write(backup,output,null);
    }
    static void write(JSONObject backup, OutputStream output,JSONArray allRecords) throws Exception {
        try(ZipOutputStream zip=new ZipOutputStream(output)) {
            text(zip,"backup.json",backup.toString(2));
            if(allRecords!=null)text(zip,"all_records.csv",csv(allRecords,"id","date","hall","kind","machine","machine_number",
                "investment_total_yen","recovery_total_yen","profit_yen","spins","work_yen","work_source",
                "work_equal_border","work_rotation_rate","work_holding_percent","work_exchange_yen","work_exchange_balls",
                "status","tag_ids","tag_names","memo"));
            for(String table:new String[]{"records","tags","sessions","operations","transfers","source_archives","edit_history","accounts","catalog","record_details","calendar_events"}) {
                JSONArray rows=backup.getJSONArray(table);
                text(zip,table+".csv",csv(rows,table.equals("tags")?"source_id":"id"));
            }
            JSONArray relations=new JSONArray();
            for(String table:new String[]{"records","sessions"}) {
                JSONArray rows=backup.getJSONArray(table);
                for(int i=0;i<rows.length();i++) {
                    JSONObject row=rows.getJSONObject(i);
                    JSONArray ids=table.equals("records")?row.optJSONArray("tag_ids"):
                        new JSONObject(row.getString("metadata")).optJSONArray("tag_ids");
                    for(String id:TagPicker.ids(ids)) relations.put(new JSONObject().put("table",table).put("record_id",row.getString("id")).put("tag_id",id));
                }
            }
            text(zip,"record_tags.csv",csv(relations,"table","record_id","tag_id"));
            JSONArray archives=SourceArchive.unpack(backup.getJSONArray("source_archives")), index=new JSONArray();
            for(int i=0;i<archives.length();i++) {
                JSONObject archive=archives.getJSONObject(i), payload=new JSONObject(archive.getString("payload"));
                String folder="sources/"+i+"/";
                index.put(new JSONObject().put("id",archive.getString("id")).put("folder",folder));
                text(zip,folder+"payload.json",payload.toString(2));
                if(payload.has("raw_entries")) text(zip,folder+"raw_entries.csv",csv(payload.getJSONArray("raw_entries"),"ordinal","type","key","declared_length","value","length_matches"));
                if(payload.has("source_pcb_base64")) write(zip,folder+"original.pcb",android.util.Base64.decode(payload.getString("source_pcb_base64"),android.util.Base64.DEFAULT));
            }
            text(zip,"source_index.csv",csv(index,"id","folder"));
            text(zip,"README.txt","遊技収支帳 全データ出力 v7\nUTF-8 BOM付きCSV。セル内の配列・オブジェクトはJSONです。\n__null_fields列はNULLの列名をJSON配列で示します。空文字とNULLを区別できます。\nall_records.csvは取込分と新規分を一つにした閲覧用一覧です。statusがcomplete以外のprofit_yenは空欄です。\nrecordsは取込・後入力の原記録、sessionsは開始・終了で作った原記録、operationsは円または数量の符号付き増減、transfersは台移動です。metadata列に機種・台番号・メモ等を保持します。\naccountsはホール・口座・評価率の入力候補です。calendar_eventsは単発・繰り返しのホールイベントです。edit_historyは明細訂正と取り消しの履歴です。record_tagsはIDによるタグ関係です。source_archivesとsourcesには取り込み元を保存します。\n復元にはZIPを展開してbackup.jsonをアプリに取り込んでください。CSV編集による復元には対応しません。\n");
        }
    }
}
