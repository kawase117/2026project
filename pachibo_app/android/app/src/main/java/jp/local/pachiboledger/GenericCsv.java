package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.ByteBuffer;
import java.math.BigDecimal;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** User-mapped UTF-8 CSV; every imported value comes from an explicit source column. */
final class GenericCsv {
    static final String[] FIELDS={"日付","投資（円）","回収（円）","ホール","機種","台番号","タグ","メモ",
        "遊技種別","稼働時間（分）","収支（照合用）"};
    private static final String[][] ALIASES={{"日付","遊技日","date","プレイ日"},
        {"投資","投資額","投資金額","investment","investment_yen","investment_total_yen"},
        {"回収","回収額","回収金額","recovery","recovery_yen","recovery_total_yen","return"},
        {"ホール","店舗","店舗名","ホール名","店名","hall","store"},
        {"機種","機種名","machine"},{"台番号","台番","machine_number"},
        {"タグ","tags","tag_names"},{"メモ","備考","memo","コメント"},
        {"種別","遊技種別","ゲーム種別","kind","game_kind"},
        {"稼働時間","稼働時間（分）","稼働時間(分)","duration_minutes"},
        {"収支","損益","profit","profit_yen"}};
    final List<List<String>> lines;
    final String fingerprint;
    final String encoding;
    final char delimiter;
    GenericCsv(byte[] bytes)throws Exception{this(bytes,StandardCharsets.UTF_8);}
    GenericCsv(byte[] bytes,Charset charset)throws Exception{
        if(bytes.length>16*1024*1024)throw new IllegalArgumentException("CSVが16MBを超えています");
        String text=charset.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        if(text.startsWith("\ufeff"))text=text.substring(1);
        encoding=charset.name();
        delimiter=detectDelimiter(text);
        lines=parse(text,delimiter);
        if(lines.isEmpty()||lines.get(0).isEmpty())throw new IllegalArgumentException("CSVの見出し行がありません");
        fingerprint=hash(bytes);
    }
    List<String> headers(){return lines.get(0);}
    int suggested(int field){
        List<String> names=headers();
        for(int i=0;i<names.size();i++)for(String alias:ALIASES[field])
            if(alias.equalsIgnoreCase(names.get(i).trim()))return i;
        return -1;
    }
    int count(){return lines.size()-1;}
    boolean matchesPRecordSample(){
        String[] expected={"日付","店舗コード","店舗","メーカー","機種コード","機種","台番号",
            "投資額","回収額","収支","メモ","稼働時間","時給"};
        if(headers().size()!=expected.length)return false;
        for(int i=0;i<expected.length;i++)if(!expected[i].equals(headers().get(i).trim()))return false;
        return true;
    }
    boolean matchesPachiEvCsv(){
        String[] expected={"date","machine","store","investment","return","profit","memo"};
        if(headers().size()!=expected.length)return false;
        for(int i=0;i<expected.length;i++)if(!expected[i].equals(headers().get(i).trim()))return false;
        return true;
    }
    String sample(int[] mapping){
        StringBuilder out=new StringBuilder("データ "+count()+"行。先頭の内容：\n");
        for(int i=1;i<lines.size()&&i<=4;i++){
            out.append(i).append("行目  ");
            for(int f=0;f<FIELDS.length;f++)if(mapping[f]>=0){
                if(f>0)out.append(" / ");
                out.append(FIELDS[f]).append('=').append(cell(lines.get(i),mapping[f]));
            }
            out.append('\n');
        }
        return out.toString();
    }
    JSONObject convert(int[] columns,Map<String,String> knownTags)throws Exception{
        if(columns.length!=FIELDS.length)throw new IllegalArgumentException("列対応が不完全です");
        java.util.Set<Integer> used=new java.util.HashSet<>();
        for(int f=0;f<columns.length;f++){
            int col=columns[f];
            if(f<5&&col<0)throw new IllegalArgumentException(FIELDS[f]+"の列を選択してください");
            if(col>=headers().size())throw new IllegalArgumentException("列番号が範囲外です");
            if(col>=0&&!used.add(col))throw new IllegalArgumentException("同じ列を複数の項目に対応付けています");
        }
        JSONArray records=new JSONArray(),tags=new JSONArray(),details=new JSONArray();Map<String,String> names=new HashMap<>(knownTags);
        for(int i=1;i<lines.size();i++){
            List<String> line=lines.get(i);
            if(line.size()==1&&line.get(0).isEmpty())continue;
            if(line.size()!=headers().size())throw new IllegalArgumentException(
                i+"行目の列数が見出しと異なります（"+line.size()+"列 / "+headers().size()+"列）");
            String date=date(cell(line,columns[0]),i);
            long investment=amount(cell(line,columns[1]),i,"投資"),recovery=amount(cell(line,columns[2]),i,"回収");
            long profit;
            try{profit=Math.subtractExact(recovery,investment);}
            catch(ArithmeticException tooLarge){throw new IllegalArgumentException(i+"行目の収支額が大きすぎます");}
            if(columns[10]>=0&&!cell(line,columns[10]).trim().isEmpty()
                &&profit!=signedAmount(cell(line,columns[10]),i,"収支"))
                throw new IllegalArgumentException(i+"行目の収支が回収額－投資額と一致しません");
            JSONArray ids=new JSONArray();
            if(columns[6]>=0)for(String raw:cell(line,columns[6]).split("[|;；、]")){
                String name=raw.trim();if(name.isEmpty())continue;
                String id=names.get(name);
                if(id==null){id="csv-tag-"+hash(name.getBytes(StandardCharsets.UTF_8));names.put(name,id);
                    tags.put(new JSONObject().put("source_id",id).put("name",name).put("type","").put("priority",""));}
                ids.put(id);
            }
            String id="csv-"+fingerprint+"-"+i;
            JSONObject row=new JSONObject().put("id",id)
                .put("date",date).put("hall",cell(line,columns[3]).trim())
                .put("kind",columns[8]<0?"未分類":gameKind(cell(line,columns[8]),i))
                .put("machine",cell(line,columns[4]).trim())
                .put("machine_number",columns[5]<0?"":cell(line,columns[5]).trim())
                .put("investment_yen",investment).put("recovery_yen",recovery).put("profit_yen",profit)
                .put("duration",columns[9]<0?"":cell(line,columns[9]).trim())
                .put("memo",columns[7]<0?"":cell(line,columns[7]))
                .put("tag_ids",ids).put("match_status","csv_unclassified")
                .put("source_item_id",fingerprint+"/"+i).put("legacy_tag_bits","");
            records.put(row);
            if(columns[9]>=0&&!cell(line,columns[9]).trim().isEmpty()){
                Long minutes=durationMinutes(cell(line,columns[9]),i);
                if(minutes!=null)details.put(new JSONObject().put("id",id).put("payload",
                    new JSONObject().put("duration_minutes",minutes).toString()));
            }
        }
        return new JSONObject().put("records",records).put("tags",tags).put("record_details",details);
    }
    private static String cell(List<String> line,int column){return column<0||column>=line.size()?"":line.get(column);}
    private static String date(String source,int line){
        try{
            String normalized=Normalizer.normalize(source.trim(),Normalizer.Form.NFKC).replace('/','-');
            return LocalDate.parse(normalized,DateTimeFormatter.ofPattern("uuuu-M-d")).toString();
        }catch(Exception e){throw new IllegalArgumentException(line+"行目の日付を読み取れません: "+source);}
    }
    private static long amount(String source,int line,String field){
        String normalized=Normalizer.normalize(source.trim(),Normalizer.Form.NFKC).replace(",","").replace("円","");
        if(!normalized.matches("[0-9]+"))throw new IllegalArgumentException(line+"行目の"+field+"額が不正です: "+source);
        try{return Long.parseLong(normalized);}catch(NumberFormatException e){throw new IllegalArgumentException(line+"行目の"+field+"額が大きすぎます");}
    }
    private static long signedAmount(String source,int line,String field){
        String normalized=Normalizer.normalize(source.trim(),Normalizer.Form.NFKC)
            .replace(",","").replace("円","");
        if(!normalized.matches("[+-]?[0-9]+"))
            throw new IllegalArgumentException(line+"行目の"+field+"が不正です: "+source);
        try{return Long.parseLong(normalized);}catch(NumberFormatException e){
            throw new IllegalArgumentException(line+"行目の"+field+"が大きすぎます");
        }
    }
    private static String gameKind(String source,int line){
        String value=source.trim();
        if(value.isEmpty())return "未分類";
        if(value.equals("スロット")||value.equals("パチスロ"))return "スロット";
        if(value.equals("パチンコ"))return "パチンコ";
        throw new IllegalArgumentException(line+"行目の遊技種別を判定できません: "+source);
    }
    private static Long durationMinutes(String source,int line){
        try{
            BigDecimal value=new BigDecimal(Normalizer.normalize(source.trim(),Normalizer.Form.NFKC));
            if(value.signum()<0)throw new NumberFormatException();
            try{return value.longValueExact();}
            catch(ArithmeticException fractional){return null;} // Preserve the raw value without rounding it.
        }catch(Exception e){throw new IllegalArgumentException(line+"行目の稼働時間が不正です: "+source);}
    }
    private static char detectDelimiter(String source){
        int commas=0,tabs=0;boolean quoted=false;
        for(int i=0;i<source.length();i++){
            char ch=source.charAt(i);if(ch=='\r'||ch=='\n')break;
            if(ch=='"')quoted=!quoted;
            else if(!quoted&&ch==',')commas++;
            else if(!quoted&&ch=='\t')tabs++;
        }
        return tabs>commas?'\t':',';
    }
    private static String hash(byte[] bytes)throws Exception{
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(bytes);StringBuilder out=new StringBuilder();
        for(byte b:digest)out.append(String.format("%02x",b&255));return out.toString();
    }
    private static List<List<String>> parse(String text,char delimiter){
        List<List<String>> rows=new ArrayList<>();List<String> row=new ArrayList<>();StringBuilder cell=new StringBuilder();
        boolean quoted=false,closed=false;
        for(int i=0;i<text.length();i++){
            char ch=text.charAt(i);
            if(quoted){if(ch=='"'){if(i+1<text.length()&&text.charAt(i+1)=='"'){cell.append('"');i++;}else{quoted=false;closed=true;}}else cell.append(ch);}
            else if(ch=='"'&&cell.length()==0&&!closed)quoted=true;
            else if(ch==delimiter){row.add(cell.toString());cell.setLength(0);closed=false;}
            else if(ch=='\n'||ch=='\r'){
                row.add(cell.toString());rows.add(row);row=new ArrayList<>();cell.setLength(0);closed=false;
                if(ch=='\r'&&i+1<text.length()&&text.charAt(i+1)=='\n')i++;
            }else if(closed&&ch!=' '&&ch!='\t')throw new IllegalArgumentException("CSVの引用符の後に不正な文字があります");
            else if(!closed)cell.append(ch);
        }
        if(quoted)throw new IllegalArgumentException("CSVの引用符が閉じられていません");
        if(cell.length()>0||!row.isEmpty()){row.add(cell.toString());rows.add(row);}
        return rows;
    }
}
