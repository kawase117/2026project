package jp.local.pachiboledger;

import java.util.Collection;

final class TagFilter {
    private TagFilter() {}
    static boolean matches(Collection<String> record, Collection<String> selected, boolean all) {
        if (selected.isEmpty()) return true;
        if (all) return record.containsAll(selected);
        for (String id : selected) if (record.contains(id)) return true;
        return false;
    }
}
