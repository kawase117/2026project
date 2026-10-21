package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Reader for the observed ぱち簿 XOR 0xFF key/value backup format. */
final class PcbReader {
    private static final Pattern ENTRY = Pattern.compile("(?:(?<=,)|\\A)(Integer|String|Boolean|Long),([A-Za-z0-9_]+),(\\d+),");
    private static final Pattern ITEM = Pattern.compile("item(\\d{8}_\\d+)_(.+)");
    private static final Pattern MASTER = Pattern.compile("(tag|machine|hall)(\\d+)_(.+)");

    private static Map<String, Map<String, String>> category() { return new LinkedHashMap<>(); }

    private static byte[] read(InputStream input) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[16384]; int count;
        while ((count = input.read(buffer)) != -1) out.write(buffer, 0, count);
        return out.toByteArray();
    }

    private static long number(String value) {
        try { return Long.parseLong(value == null ? "0" : value); }
        catch (NumberFormatException ignored) { return 0; }
    }

    private static String value(Map<String, String> fields, String key) { return fields.getOrDefault(key, ""); }

    private static String rateKind(Map<String,String> item,Map<String,String> hall) {
        Set<String> observed=observedRates(item);
        boolean slot=false,pachi=false;
        for(String side:new String[]{"invest","recovery"}) {
            String slotRate=value(hall,side+"_conversion_slot");
            String pachiRate=value(hall,side+"_conversion_pachi");
            slot|=!slotRate.isEmpty()&&!"0".equals(slotRate)&&observed.contains(slotRate);
            pachi|=!pachiRate.isEmpty()&&!"0".equals(pachiRate)&&observed.contains(pachiRate);
        }
        return slot==pachi?"":slot?"スロット":"パチンコ";
    }

    private static Set<String> observedRates(Map<String,String> item) {
        Set<String> observed=new HashSet<>();
        for(String side:new String[]{"invest","recovery"}) {
            String rate=value(item,side+"_conversion");
            if(!rate.isEmpty()&&!"0".equals(rate))observed.add(rate);
        }
        return observed;
    }

    private static String historicalRateKind(Map<String,String> item,Map<String,Set<String>> rateKinds) {
        Set<String> kinds=new HashSet<>();
        for(String rate:observedRates(item)) kinds.addAll(rateKinds.getOrDefault(rate,java.util.Collections.emptySet()));
        return kinds.size()==1?kinds.iterator().next():"";
    }

    static JSONObject parse(InputStream input) throws Exception {
        byte[] bytes = read(input);
        String original = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP);
        byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder fingerprint = new StringBuilder();
        for (byte b : digest) fingerprint.append(String.format("%02x", b & 255));
        for (int i = 0; i < bytes.length; i++) bytes[i] = (byte)(bytes[i] ^ 0xFF);
        String decoded = new String(bytes, StandardCharsets.UTF_8);
        Matcher matcher = ENTRY.matcher(decoded);
        List<int[]> spans = new ArrayList<>();
        List<String> keys = new ArrayList<>();
        List<Integer> lengths = new ArrayList<>();
        List<String> types = new ArrayList<>();
        while (matcher.find()) {
            spans.add(new int[]{matcher.start(), matcher.end()});
            keys.add(matcher.group(2));
            lengths.add(Integer.parseInt(matcher.group(3)));
            types.add(matcher.group(1));
        }
        Map<String, Map<String, String>> items = category(), tags = category(), machines = category(), halls = category();
        int badLengths = 0;
        JSONArray rawEntries = new JSONArray();
        for (int i = 0; i < spans.size(); i++) {
            int end = i + 1 < spans.size() ? spans.get(i + 1)[0] - 1 : decoded.length();
            String text = decoded.substring(spans.get(i)[1], end);
            rawEntries.put(new JSONObject().put("ordinal",i).put("type",types.get(i)).put("key",keys.get(i))
                .put("declared_length",lengths.get(i)).put("value",text).put("length_matches",text.length()==lengths.get(i)));
            if (text.length() != lengths.get(i)) badLengths++; // Java String.length is UTF-16 units.
            Matcher item = ITEM.matcher(keys.get(i));
            if (item.matches()) {
                items.computeIfAbsent(item.group(1), k -> new HashMap<>()).put(item.group(2), text);
                continue;
            }
            Matcher master = MASTER.matcher(keys.get(i));
            if (master.matches()) {
                Map<String, Map<String, String>> target = master.group(1).equals("tag") ? tags
                    : master.group(1).equals("machine") ? machines : halls;
                target.computeIfAbsent(master.group(2), k -> new HashMap<>()).put(master.group(3), text);
            }
        }
        JSONArray tagList = new JSONArray();
        for (Map.Entry<String, Map<String, String>> entry : tags.entrySet()) {
            if (value(entry.getValue(), "name").isEmpty()) continue;
            JSONObject tag = new JSONObject();
            tag.put("source_id", entry.getKey());
            for (String key : new String[]{"name", "type", "priority"}) tag.put(key, value(entry.getValue(), key));
            tagList.put(tag);
        }
        // A hall master holds only its latest rates. Learn older rates from records
        // whose hall master identifies exactly one game kind, without assuming that
        // a numeric rate (for example 500) means the same thing in every backup.
        Map<String,Set<String>> rateKinds=new HashMap<>();
        for(Map<String,String> fields:items.values())if("1".equals(value(fields,"type"))){
            String kind=rateKind(fields,halls.getOrDefault(value(fields,"hall_id"),java.util.Collections.emptyMap()));
            if(!kind.isEmpty())for(String rate:observedRates(fields))
                rateKinds.computeIfAbsent(rate,key->new HashSet<>()).add(kind);
        }
        Map<String,Set<String>> machineKinds=new HashMap<>();
        for(Map<String,String> fields:items.values())if("1".equals(value(fields,"type"))){
            String kind=rateKind(fields,halls.getOrDefault(value(fields,"hall_id"),java.util.Collections.emptyMap()));
            if(kind.isEmpty())kind=historicalRateKind(fields,rateKinds);
            if(!kind.isEmpty()&&!value(fields,"machine_id").isEmpty())
                machineKinds.computeIfAbsent(value(fields,"machine_id"),key->new HashSet<>()).add(kind);
        }
        JSONArray records = new JSONArray();
        int invalidDates = 0;
        int directKinds=0,historicalKinds=0,inferredKinds=0;
        for (Map.Entry<String, Map<String, String>> entry : items.entrySet()) {
            String id = entry.getKey(); Map<String, String> fields = entry.getValue();
            boolean typeOne = "1".equals(value(fields, "type"));
            boolean missingType = !fields.containsKey("type") && fields.containsKey("invest") && fields.containsKey("recovery");
            if (!typeOne && !missingType) continue;
            String compactDate = id.substring(0, 8);
            String date = compactDate.substring(0, 4) + "-" + compactDate.substring(4, 6) + "-" + compactDate.substring(6, 8);
            try { LocalDate.parse(date); }
            catch (Exception ignored) { invalidDates++; continue; }
            String hallName = value(halls.getOrDefault(value(fields, "hall_id"), java.util.Collections.emptyMap()), "name");
            String machineName = value(machines.getOrDefault(value(fields, "machine_id"), java.util.Collections.emptyMap()), "name");
            long invested = number(fields.get("invest")) + number(fields.get("invest2"));
            long recovered = number(fields.get("recovery")) + number(fields.get("recovery2"));
            JSONArray ids = new JSONArray();
            int tagCount = (int)Math.min(Math.max(number(fields.get("tag_count")), 0), 100);
            for (int n = 0; n < tagCount; n++) if (fields.containsKey("tag" + n)) ids.put(fields.get("tag" + n));
            JSONObject row = new JSONObject();
            row.put("id", "pcb-" + id); row.put("date", date);
            String kind=rateKind(fields,halls.getOrDefault(value(fields,"hall_id"),java.util.Collections.emptyMap()));
            if(!kind.isEmpty())directKinds++;
            else {
                kind=historicalRateKind(fields,rateKinds);
                if(!kind.isEmpty())historicalKinds++;
                else {
                    Set<String> inferred=machineKinds.get(value(fields,"machine_id"));
                    if(inferred!=null&&inferred.size()==1){kind=inferred.iterator().next();inferredKinds++;}
                }
            }
            row.put("hall", hallName); row.put("kind", kind.isEmpty()?"未分類":kind); row.put("machine", machineName);
            row.put("machine_number", value(fields, "number"));
            row.put("investment_yen", invested); row.put("recovery_yen", recovered);
            row.put("profit_yen", recovered - invested);
            row.put("duration", value(fields, "time")); row.put("memo", value(fields, "memo"));
            row.put("legacy_start",value(fields,"start")); row.put("legacy_end",value(fields,"end"));
            row.put("tag_ids", ids); row.put("match_status", typeOne ? "pcb_direct" : "pcb_type_missing");
            row.put("source_item_id", id); row.put("legacy_tag_bits", value(fields, "tag"));
            records.put(row);
        }
        JSONObject audit = new JSONObject();
        audit.put("items", items.size()); audit.put("play_records", records.length());
        audit.put("bad_length_fields", badLengths);
        audit.put("play_like_invalid_dates", invalidDates);
        audit.put("game_kind_from_hall_rate",directKinds);
        audit.put("game_kind_from_historical_rate",historicalKinds);
        audit.put("game_kind_from_machine_id",inferredKinds);
        int reviewRequired = 0;
        for (int i = 0; i < records.length(); i++) if ("pcb_type_missing".equals(records.getJSONObject(i).optString("match_status"))) reviewRequired++;
        audit.put("review_required_records", reviewRequired);
        JSONObject result = new JSONObject();
        result.put("format", "pachibo-ledger-v1"); result.put("tags", tagList);
        result.put("records", records); result.put("audit", audit);
        result.put("source_sha256", fingerprint.toString()); result.put("source_pcb_base64", original);
        result.put("raw_entries", rawEntries);
        return result;
    }
}
