package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
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
    static final String[] FIELDS={"日付","投資（円）","回収（円）","ホール","機種","台番号","タグ","メモ"};
    private static final String[][] ALIASES={{"日付","遊技日","date"},{"投資","投資額","investment","investment_yen"},
        {"回収","回収額","recovery","recovery_yen"},{"ホール","店舗","hall"},{"機種","machine"},
        {"台番号","台番","machine_number"},{"タグ","tags","tag_names"},{"メモ","備考","memo"}};
    final List<List<String>> lines;
    final String fingerprint;
    GenericCsv(byte[] bytes)throws Exception{
        if(bytes.length>16*1024*1024)throw new IllegalArgumentException("CSVが16MBを超えています");
        String text=new String(bytes,StandardCharsets.UTF_8);
        if(text.indexOf('\ufffd')>=0)throw new IllegalArgumentException("CSVをUTF-8で読み取れませんでした");
        if(text.startsWith("\ufeff"))text=text.substring(1);
        lines=parse(text);
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
        JSONArray records=new JSONArray(),tags=new JSONArray();Map<String,String> names=new HashMap<>(knownTags);
        for(int i=1;i<lines.size();i++){
            List<String> line=lines.get(i);
            if(line.size()==1&&line.get(0).isEmpty())continue;
            String date=date(cell(line,columns[0]),i);
            long investment=amount(cell(line,columns[1]),i,"投資"),recovery=amount(cell(line,columns[2]),i,"回収");
            long profit=Math.subtractExact(recovery,investment);
            JSONArray ids=new JSONArray();
            if(columns[6]>=0)for(String raw:cell(line,columns[6]).split("[|;；、]")){
                String name=raw.trim();if(name.isEmpty())continue;
                String id=names.get(name);
                if(id==null){id="csv-tag-"+hash(name.getBytes(StandardCharsets.UTF_8));names.put(name,id);
                    tags.put(new JSONObject().put("source_id",id).put("name",name).put("type","").put("priority",""));}
                ids.put(id);
            }
            JSONObject row=new JSONObject().put("id","csv-"+fingerprint+"-"+i)
                .put("date",date).put("hall",cell(line,columns[3]).trim())
                .put("kind","未分類").put("machine",cell(line,columns[4]).trim())
                .put("machine_number",columns[5]<0?"":cell(line,columns[5]).trim())
                .put("investment_yen",investment).put("recovery_yen",recovery).put("profit_yen",profit)
                .put("duration","").put("memo",columns[7]<0?"":cell(line,columns[7]))
                .put("tag_ids",ids).put("match_status","csv_unclassified")
                .put("source_item_id",fingerprint+"/"+i).put("legacy_tag_bits","");
            records.put(row);
        }
        return new JSONObject().put("records",records).put("tags",tags);
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
    private static String hash(byte[] bytes)throws Exception{
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(bytes);StringBuilder out=new StringBuilder();
        for(byte b:digest)out.append(String.format("%02x",b&255));return out.toString();
    }
    private static List<List<String>> parse(String text){
        List<List<String>> rows=new ArrayList<>();List<String> row=new ArrayList<>();StringBuilder cell=new StringBuilder();
        boolean quoted=false,closed=false;
        for(int i=0;i<text.length();i++){
            char ch=text.charAt(i);
            if(quoted){if(ch=='"'){if(i+1<text.length()&&text.charAt(i+1)=='"'){cell.append('"');i++;}else{quoted=false;closed=true;}}else cell.append(ch);}
            else if(ch=='"'&&cell.length()==0&&!closed)quoted=true;
            else if(ch==','){row.add(cell.toString());cell.setLength(0);closed=false;}
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
