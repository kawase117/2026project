package jp.local.pachiboledger;

import java.util.*;

public final class TagFilterTest {
    public static void main(String[] args) {
        List<String> record=Arrays.asList("id,comma","id-newline\n","emoji-🎰");
        check(TagFilter.matches(record,List.of(),true));
        check(TagFilter.matches(record,List.of(),false));
        check(TagFilter.matches(record,List.of("id,comma"),true));
        check(!TagFilter.matches(record,List.of("id"),false));
        check(TagFilter.matches(record,List.of("id,comma","emoji-🎰"),true));
        check(!TagFilter.matches(record,List.of("id,comma","missing"),true));
        check(TagFilter.matches(record,List.of("id,comma","missing"),false));
        check(!TagFilter.matches(List.of(),List.of("id,comma"),false));
        check(TagFilter.matches(record,List.of("id-newline\n"),true));
        check(TagFilter.matches(record,List.of("id,comma","id,comma"),true));
        System.out.println("PASS 10 exact tag AND/OR assertions");
    }
    private static void check(boolean condition) { if(!condition) throw new AssertionError("Tag filter mismatch"); }
}
