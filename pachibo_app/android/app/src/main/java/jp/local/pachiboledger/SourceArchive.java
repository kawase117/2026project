package jp.local.pachiboledger;

import org.json.*;
import java.util.*;

/** Keep each SQLite cursor row small; concatenate only when exporting a source archive. */
final class SourceArchive {
    static JSONArray pack(String sourceId,String payload) throws Exception {
        List<String> chunks=new ArrayList<>();
        for(int start=0;start<payload.length();) {
            int end=Math.min(start+65536,payload.length());
            if(end<payload.length()&&Character.isHighSurrogate(payload.charAt(end-1))) end--;
            chunks.add(payload.substring(start,end)); start=end;
        }
        JSONArray result=new JSONArray();
        for(int i=0;i<chunks.size();i++) {
            JSONObject chunk=new JSONObject().put("archive_chunk_v1",true).put("source_id",sourceId)
                .put("index",i).put("count",chunks.size()).put("content",chunks.get(i));
            result.put(new JSONObject().put("id",sourceId+"#"+i).put("payload",chunk.toString()));
        }
        return result;
    }
    static JSONArray unpack(JSONArray rows) throws Exception {
        JSONArray result=new JSONArray(); Map<String,SortedMap<Integer,String>> groups=new LinkedHashMap<>();
        Map<String,Integer> counts=new HashMap<>();
        for(int i=0;i<rows.length();i++) {
            JSONObject row=rows.getJSONObject(i), payload=new JSONObject(row.getString("payload"));
            if(!payload.optBoolean("archive_chunk_v1",false)) { result.put(row); continue; }
            String id=payload.getString("source_id"); int count=payload.getInt("count"), index=payload.getInt("index");
            if(count<=0||index<0||index>=count||(counts.containsKey(id)&&counts.get(id)!=count)) throw new IllegalArgumentException("原本分割情報が不正です");
            counts.put(id,count);
            if(groups.computeIfAbsent(id,k->new TreeMap<>()).put(index,payload.getString("content"))!=null) throw new IllegalArgumentException("原本の分割が重複しています");
        }
        for(Map.Entry<String,SortedMap<Integer,String>> entry:groups.entrySet()) {
            if(entry.getValue().size()!=counts.get(entry.getKey())) throw new IllegalArgumentException("原本の分割データが不足しています");
            StringBuilder payload=new StringBuilder(); for(String chunk:entry.getValue().values()) payload.append(chunk);
            result.put(new JSONObject().put("id",entry.getKey()).put("payload",payload.toString()));
        }
        return result;
    }
}
