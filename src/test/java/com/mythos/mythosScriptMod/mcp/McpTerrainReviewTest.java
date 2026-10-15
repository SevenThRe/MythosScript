package com.mythos.mythosScriptMod.mcp;
import com.mythos.mythosScriptMod.utils.TerrainBlockReview.Receipt;
import org.junit.Test;
import static org.junit.Assert.*;
public class McpTerrainReviewTest {
    @Test public void requestAndUnrelatedPacketsNeverConfirm() {
        Receipt r = new Receipt(); Object c = new Object();
        assertTrue(r.begin(c, 12, "stone", 0));
        assertFalse(r.begin(c, 13, "stone", 1));
        r.receive(c, 12, "air", "single", 1); assertTrue(r.pending());
        r.sent(new Object(), 12); r.receive(c, 12, "air", "single", 2); assertTrue(r.pending());
        r.sent(c, 12); r.receive(c, 13, "air", "single", 3); assertTrue(r.pending());
        r.receive(new Object(), 12, "air", "single", 4); assertTrue(r.pending());
        r.receive(c, 12, "air", "single", 5);
        assertEquals("server_block_update", r.snapshot().get("status").getAsString());
        assertEquals("air", r.snapshot().get("serverReported").getAsString());
        assertFalse(r.snapshot().get("hiddenWorldTruthVerified").getAsBoolean());
    }
    @Test public void lateReplyDoesNotTurnTimeoutIntoSuccess() {
        Receipt r = new Receipt(); Object c = new Object(); r.begin(c, 1, "stone", 0); r.sent(c, 1);
        r.receive(c, 1, "ore", "multi", 5000000000L);
        assertEquals("timeout", r.snapshot().get("status").getAsString());
        assertFalse(r.snapshot().has("serverReported"));
    }
    @Test public void changedWorldCancelsAndSnapshotsAreDetached() {
        Receipt r = new Receipt(); Object c = new Object(); r.begin(c, 1, "stone", 0); r.sent(c, 1);
        r.snapshot().addProperty("status", "forged"); assertTrue(r.pending());
        r.cancel("world_changed"); r.receive(c, 1, "ore", "single", 2);
        assertEquals("world_changed", r.snapshot().get("status").getAsString());
    }
    @Test public void worldTransitionInvalidatesEvenAnAlreadyReceivedResult() {
        Receipt r = new Receipt(); Object c = new Object(); r.begin(c, 1, "stone", 0); r.sent(c, 1);
        r.receive(c, 1, "ore", "single", 1); r.worldChanged();
        assertEquals("world_changed", r.snapshot().get("status").getAsString());
        assertFalse(r.snapshot().get("worldStillMatches").getAsBoolean());
    }
    @Test public void sameStateIsStillAReceiptNotTruth() {
        Receipt r = new Receipt(); Object c = new Object(); r.begin(c, 1, "stone", 0); r.sent(c, 1);
        r.receive(c, 1, "stone", "multi", 10);
        assertEquals("stone", r.snapshot().get("serverReported").getAsString());
        assertFalse(r.snapshot().get("clientAppliedVerified").getAsBoolean());
        assertFalse(r.pending());
    }
}
