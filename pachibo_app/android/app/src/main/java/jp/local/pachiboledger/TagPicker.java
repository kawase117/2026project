package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.*;
import java.util.function.Consumer;

/** IDs are the relationship; punctuation in names is never parsed as a separator. */
final class TagPicker {
    static Set<String> ids(JSONArray input) {
        Set<String> result = new LinkedHashSet<>();
        if (input != null) for (int i=0;i<input.length();i++) result.add(input.optString(i));
        return result;
    }
    static JSONArray array(Collection<String> ids) { JSONArray result=new JSONArray(); for(String id:ids) result.put(id); return result; }
    static Map<String,String> names(LedgerDb db) throws Exception {
        Map<String,String> result=new LinkedHashMap<>(); JSONArray tags=db.tags();
        for(int i=0;i<tags.length();i++) { JSONObject tag=tags.getJSONObject(i); result.put(tag.getString("source_id"),tag.getString("name")); }
        return result;
    }
    static String display(LedgerDb db, JSONArray ids) throws Exception {
        Map<String,String> names=names(db); List<String> labels=new ArrayList<>();
        for(String id:ids(ids)) labels.add("「"+names.getOrDefault(id,"未解決タグ "+id)+"」");
        return labels.isEmpty()?"なし":String.join(" ",labels);
    }
    static void show(Activity activity, LedgerDb db, Collection<String> current, boolean allowCreate, Consumer<Set<String>> save) {
        try {
            Map<String,String> tags=names(db); Set<String> chosen=new LinkedHashSet<>(current);
            for(String id:current) tags.putIfAbsent(id,"未解決タグ "+id);
            LinearLayout panel=new LinearLayout(activity); panel.setOrientation(1); panel.setPadding(20,10,20,10);
            ScrollView scroll=new ScrollView(activity); scroll.addView(panel);
            LinearLayout choices=new LinearLayout(activity); choices.setOrientation(1); panel.addView(choices);
            for(Map.Entry<String,String> tag:tags.entrySet()) addChoice(activity,choices,tag.getKey(),tag.getValue(),chosen);
            if(allowCreate) {
                EditText name=new EditText(activity); name.setHint("新しいタグ名（1件）"); name.setSingleLine(true); panel.addView(name);
                Button add=new Button(activity); add.setText("タグを作成して選択"); panel.addView(add);
                add.setOnClickListener(v->{
                    String value=name.getText().toString().trim();
                    if(value.isEmpty()) { name.setError("タグ名を入力してください"); return; }
                    try {
                        String id=db.tagId(value); chosen.add(id);
                        if(!tags.containsKey(id)) { tags.put(id,value); addChoice(activity,choices,id,value,chosen); }
                        else for(int i=0;i<choices.getChildCount();i++) {
                            CheckBox box=(CheckBox)choices.getChildAt(i); if(id.equals(box.getTag())) box.setChecked(true);
                        }
                        name.setText("");
                    } catch(Exception e) { name.setError(e.getMessage()); }
                });
            }
            new AlertDialog.Builder(activity).setTitle("タグを選択").setView(scroll)
                .setPositiveButton("適用",(d,w)->save.accept(new LinkedHashSet<>(chosen)))
                .setNegativeButton("戻る",null).show();
        } catch(Exception e) { new AlertDialog.Builder(activity).setMessage(e.getMessage()).setPositiveButton("閉じる",null).show(); }
    }
    private static void addChoice(Activity activity,LinearLayout parent,String id,String name,Set<String> chosen) {
        CheckBox box=new CheckBox(activity); box.setTag(id); box.setText(name); box.setChecked(chosen.contains(id));
        box.setOnCheckedChangeListener((v,checked)->{ if(checked) chosen.add(id); else chosen.remove(id); }); parent.addView(box);
    }
}
