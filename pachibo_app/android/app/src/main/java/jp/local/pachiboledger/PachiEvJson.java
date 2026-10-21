package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONObject;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

/** Import the backup shape emitted by the published pachi-ev-analyzer exporter. */
final class PachiEvJson {
    private PachiEvJson(){}
    static JSONObject convert(JSONObject input)throws Exception{
        if(input.has("format")||!input.has("records")||input.optJSONObject("settings")==null)throw new IllegalArgumentException(
            "pachi-ev-analyzerのJSONではありません。アプリ自身のJSONは『JSONを読み込む』を選んでください");
        JSONArray original=input.getJSONArray("records"),records=new JSONArray(),details=new JSONArray();
        Set<String> ids=new HashSet<>();
        for(int i=0;i<original.length();i++){
            JSONObject item=original.getJSONObject(i);
            String sourceId=requiredString(item,"id",i),date=requiredString(item,"date",i);
            try{LocalDate.parse(date);}
            catch(Exception invalid){throw new IllegalArgumentException((i+1)+"件目の日付が不正です: "+date);}
            if(!ids.add(sourceId))throw new IllegalArgumentException((i+1)+"件目のIDが重複しています: "+sourceId);
            String hall=requiredString(item,"hall",i),machine=requiredString(item,"machine",i);
            String type=requiredString(item,"type",i);
            if(!"玉".equals(type)&&!"枚".equals(type))throw new IllegalArgumentException((i+1)+"件目の遊技種別が不正です");
            long investment=money(item,"investment",i),recovery=money(item,"recovery",i);
            long profit;
            try{profit=Math.subtractExact(recovery,investment);}
            catch(ArithmeticException overflow){throw new IllegalArgumentException((i+1)+"件目の収支額が大きすぎます");}
            String id="pachi-ev-"+UUID.nameUUIDFromBytes(sourceId.getBytes(StandardCharsets.UTF_8));
            JSONObject row=new JSONObject().put("id",id).put("date",date)
                .put("hall",hall).put("kind","枚".equals(type)?"スロット":"パチンコ")
                .put("machine",machine).put("machine_number","")
                .put("investment_yen",investment).put("recovery_yen",recovery).put("profit_yen",profit)
                .put("duration","").put("memo",item.optString("memo",""))
                .put("tag_ids",new JSONArray()).put("match_status","external_json")
                .put("source_item_id",sourceId).put("legacy_tag_bits","");
            records.put(row);
            details.put(new JSONObject().put("id",id).put("payload",new JSONObject()
                .put("source_app","pachi-ev-analyzer").put("source_original",item).toString()));
        }
        String payload=input.toString();byte[] digest=MessageDigest.getInstance("SHA-256")
            .digest(payload.getBytes(StandardCharsets.UTF_8));StringBuilder key=new StringBuilder("pachi-ev-");
        for(byte b:digest)key.append(String.format("%02x",b&255));
        return new JSONObject().put("records",records).put("tags",new JSONArray())
            .put("record_details",details).put("source_archives",SourceArchive.pack(key.toString(),payload));
    }
    private static String requiredString(JSONObject row,String key,int index)throws Exception{
        Object value=row.opt(key);
        if(!(value instanceof String)||((String)value).trim().isEmpty())
            throw new IllegalArgumentException((index+1)+"件目の"+key+"がありません");
        return (String)value;
    }
    private static long money(JSONObject row,String key,int index)throws Exception{
        Object value=row.opt(key);
        if(!(value instanceof Number))throw new IllegalArgumentException((index+1)+"件目の"+key+"は数値である必要があります");
        try{
            long amount=new BigDecimal(value.toString()).longValueExact();
            if(amount<0)throw new ArithmeticException();
            return amount;
        }catch(ArithmeticException invalid){throw new IllegalArgumentException((index+1)+"件目の"+key+"は0以上の整数（円）である必要があります");}
    }
}
