package jp.local.pachiboledger;

import java.util.*;

public final class AccountingTest {
    private static int checks;
    private static void eq(Object actual, Object expected) {
        checks++;
        if (!Objects.equals(actual, expected)) throw new AssertionError(actual + " != " + expected);
    }
    private static void rejects(Runnable action) {
        checks++;
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected rejection");
    }
    public static void main(String[] args) {
        Accounting.Rate rate = new Accounting.Rate(20, 1);
        List<Accounting.Entry> entries = new ArrayList<>();
        entries.add(Accounting.Entry.cash("c1", "A", -10000));
        entries.add(Accounting.Entry.cash("c2", "B", 16000));
        for (Long quantity : Arrays.asList(0L, 1L, 600L, 1000L, null)) {
            Accounting.Transfer transfer = new Accounting.Transfer("t", "A", "B", quantity, rate);
            Accounting.Result total = Accounting.calculate(entries, List.of(transfer), Set.of("A", "B"));
            eq(total.evaluated.roundYen().toString(), "6000");
            eq(total.cash.toString(), "6000");
            Accounting.Result a = Accounting.calculate(entries, List.of(transfer), Set.of("A"));
            if (quantity == null) eq(a.evaluated, null);
            else eq(a.evaluated.roundYen().longValueExact(), quantity * 20 - 10000);
        }
        Accounting.Rate nonEqual = new Accounting.Rate(1000, 56);
        List<Accounting.Entry> stored = List.of(
            Accounting.Entry.quantity("q1", "A", -100, nonEqual),
            Accounting.Entry.quantity("q2", "A", 156, nonEqual));
        eq(Accounting.calculate(stored, List.of(), Set.of("A")).evaluated.roundYen().toString(), "1000");
        eq(Accounting.calculate(stored, List.of(), Set.of("A")).cash.toString(), "0");
        for (long[] example : new long[][] {
            {5000, 8000, 0, 0, 3000}, {0, 0, 300, 500, 4000},
            {5000, 0, 100, 400, 1000}, {5000, 6000, 0, 200, 5000},
            {0, 0, 105, 150, 900}
        }) {
            Accounting.Result result = Accounting.calculate(List.of(
                Accounting.Entry.cash("in", "A", -example[0]),
                Accounting.Entry.cash("out", "A", example[1]),
                Accounting.Entry.quantity("replay", "A", -example[2], rate),
                Accounting.Entry.quantity("deposit", "A", example[3], rate)
            ), List.of(), Set.of("A"));
            eq(result.evaluated.roundYen().longValueExact(), example[4]);
            eq(result.cash.longValueExact(), example[1] - example[0]);
        }
        Accounting.Transfer unknown = new Accounting.Transfer("unknown", "A", "B", null, null);
        eq(Accounting.calculate(entries, List.of(unknown), Set.of("B")).unresolvedIds, Set.of("unknown"));
        rejects(() -> Accounting.calculate(entries, List.of(unknown, unknown), Set.of("A", "B")));
        eq(new Accounting.Amount(1, 2).roundYen().toString(), "1");
        eq(new Accounting.Amount(-1, 2).roundYen().toString(), "-1");
        eq(new Accounting.Amount(1, 3).add(new Accounting.Amount(1, 3)).roundYen().toString(), "1");
        eq(Accounting.calculate(List.of(Accounting.Entry.quantity("u", "A", 100, null)), List.of(), Set.of("A")).evaluated, null);
        eq(Accounting.calculate(List.of(), List.of(), Set.of()).evaluated, null);
        eq(Accounting.calculate(List.of(Accounting.Entry.cash("zero", "A", 0)), List.of(), Set.of("A")).evaluated.roundYen().toString(), "0");
        rejects(() -> new Accounting.Rate(1, 0));
        rejects(() -> new Accounting.Rate(-1, 2));
        rejects(() -> new Accounting.Transfer("t", "A", "A", 1L, rate));
        rejects(() -> new Accounting.Transfer("t", "A", "B", -1L, rate));
        rejects(() -> Accounting.calculate(List.of(entries.get(0), entries.get(0)), List.of(), Set.of("A")));
        eq(new Accounting.Amount(Long.MAX_VALUE, 1).add(new Accounting.Amount(Long.MAX_VALUE, 1)).roundYen().toString(), "18446744073709551614");
        System.out.println("PASS " + checks + " accounting assertions");
    }
}
