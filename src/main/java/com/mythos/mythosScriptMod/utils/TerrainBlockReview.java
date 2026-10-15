package com.mythos.mythosScriptMod.utils;

import com.google.gson.JsonObject;
import io.netty.channel.Channel;
import net.minecraft.block.state.IBlockState;
import net.minecraft.client.Minecraft;
import net.minecraft.client.resources.I18n;
import net.minecraft.network.play.client.CPacketPlayerTryUseItemOnBlock;
import net.minecraft.network.play.server.SPacketBlockChange;
import net.minecraft.network.play.server.SPacketMultiBlockChange;
import net.minecraft.util.EnumHand;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.RayTraceResult;
import net.minecraft.util.math.Vec3d;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;

/** One native empty-hand interaction; a matching packet is evidence of delivery, not hidden world truth. */
public final class TerrainBlockReview {
    public static final TerrainBlockReview INSTANCE = new TerrainBlockReview();
    private final Receipt receipt = new Receipt();
    private Object world;
    private long lastStart;
    private java.nio.file.Path output;
    private boolean saved = true;
    private volatile String lastAttemptError = "";

    /** Independent of Minecraft so ordering, identity and timeout semantics are regression tested. */
    public static final class Receipt {
        private Object channel;
        private long position, started;
        private boolean sent;
        private JsonObject data = new JsonObject();
        public synchronized boolean begin(Object connection, long pos, String before, long now) {
            if (pending()) return false;
            channel = connection; position = pos; started = now; sent = false;
            data = new JsonObject();
            data.addProperty("status", "waiting"); data.addProperty("position", pos);
            data.addProperty("before", before); data.addProperty("startedNanos", now);
            data.addProperty("hiddenWorldTruthVerified", false);
            data.addProperty("correlation", "same_connection_position_after_native_interaction_no_request_id");
            return true;
        }
        public synchronized boolean pending() { return data.has("status") && "waiting".equals(data.get("status").getAsString()); }
        public synchronized void sent(Object connection, long pos) {
            if (pending() && channel == connection && position == pos) { sent = true; data.addProperty("outboundObserved", true); }
        }
        public synchronized void receive(Object connection, long pos, String state, String packet, long now) {
            expire(now);
            if (pending() && sent && channel == connection && position == pos) {
                data.addProperty("status", "server_block_update"); data.addProperty("serverReported", state);
                data.addProperty("packet", packet); data.addProperty("elapsedMs", (now - started) / 1000000L);
                data.addProperty("clientAppliedVerified", false);
            }
        }
        public synchronized void expire(long now) {
            if (pending() && now - started >= 5000000000L) cancel("timeout");
        }
        public synchronized void worldChanged() {
            if (data.has("status")) {
                data.addProperty("status", "world_changed");
                data.addProperty("worldStillMatches", false);
            }
        }
        public synchronized void cancel(String reason) { if (pending()) data.addProperty("status", reason); }
        public synchronized void metadata(int x, int y, int z, int dimension, String action) {
            data.addProperty("x", x); data.addProperty("y", y); data.addProperty("z", z);
            data.addProperty("dimension", dimension); data.addProperty("action", action);
            data.addProperty("timestamp", System.currentTimeMillis());
            data.addProperty("observationStage", "network_received_before_client_filters_and_application");
        }
        public synchronized JsonObject snapshot() { return new com.google.gson.JsonParser().parse(data.toString()).getAsJsonObject(); }
    }

    public JsonObject snapshot() {
        JsonObject result = receipt.snapshot();
        if (!lastAttemptError.isEmpty()) result.addProperty("lastAttemptError", lastAttemptError);
        return result;
    }
    public String label() {
        JsonObject data = snapshot();
        if (!lastAttemptError.isEmpty()) return I18n.format("terrain.review." + lastAttemptError);
        String status = data.has("status") ? data.get("status").getAsString() : "idle";
        return I18n.format("terrain.review." + status) + (data.has("serverReported") ? " " + data.get("serverReported").getAsString() : "");
    }

    public void request(boolean underfoot) {
        Minecraft mc = Minecraft.getMinecraft();
        String error = null;
        long now = System.nanoTime();
        if (mc.player == null || mc.world == null || mc.getConnection() == null) error = "no_world";
        else if (receipt.pending()) error = "busy";
        else if (lastStart != 0 && now - lastStart < 1000000000L) error = "cooldown";
        else if (!mc.player.getHeldItemMainhand().isEmpty()) error = "empty_hand";
        if (error != null) { message(error); return; }
        double reach = mc.playerController.getBlockReachDistance();
        Vec3d eye = mc.player.getPositionEyes(1F);
        RayTraceResult hit;
        if (underfoot) {
            BlockPos below = new BlockPos(mc.player.posX, mc.player.getEntityBoundingBox().minY - 0.01, mc.player.posZ);
            hit = mc.world.rayTraceBlocks(eye, new Vec3d(below).addVector(0.5, 0.01, 0.5), false, false, false);
            if (hit == null || !below.equals(hit.getBlockPos())) { message("no_target"); return; }
        } else hit = mc.player.rayTrace(reach, 1F);
        if (hit == null || hit.typeOfHit != RayTraceResult.Type.BLOCK || hit.sideHit == null
                || eye.squareDistanceTo(hit.hitVec) > reach * reach || !mc.world.isBlockLoaded(hit.getBlockPos())) {
            message("no_target"); return;
        }
        lastAttemptError = "";
        BlockPos pos = hit.getBlockPos();
        Channel channel = mc.getConnection().getNetworkManager().channel();
        world = mc.world; lastStart = now;
        if (!receipt.begin(channel, pos.toLong(), mc.world.getBlockState(pos).toString(), now)) return;
        receipt.metadata(pos.getX(), pos.getY(), pos.getZ(), mc.player.dimension, underfoot ? "underfoot_right_click" : "crosshair_right_click");
        output = com.mythos.mythosScriptMod.system.ProfileManager.getCurrentProfileDir().resolve("terrain")
                .resolve("review-" + System.currentTimeMillis() + ".json");
        saved = false;
        try {
            mc.playerController.processRightClickBlock(mc.player, mc.world, pos, hit.sideHit, hit.hitVec, EnumHand.MAIN_HAND);
        } catch (RuntimeException e) { receipt.cancel("failed"); }
    }
    private void message(String reason) {
        lastAttemptError = reason;
        Minecraft mc = Minecraft.getMinecraft();
        if (mc.player != null) mc.player.sendMessage(new net.minecraft.util.text.TextComponentString(I18n.format("terrain.review." + reason)));
    }
    public void packet(Channel channel, Object packet, boolean outbound) {
        if (!receipt.pending()) return;
        if (outbound && packet instanceof CPacketPlayerTryUseItemOnBlock) {
            CPacketPlayerTryUseItemOnBlock p = (CPacketPlayerTryUseItemOnBlock) packet;
            if (p.getHand() == EnumHand.MAIN_HAND) receipt.sent(channel, p.getPos().toLong());
        } else if (!outbound && packet instanceof SPacketBlockChange) {
            SPacketBlockChange p = (SPacketBlockChange) packet;
            receive(channel, p.getBlockPosition(), p.getBlockState(), "SPacketBlockChange");
        } else if (!outbound && packet instanceof SPacketMultiBlockChange) {
            for (SPacketMultiBlockChange.BlockUpdateData p : ((SPacketMultiBlockChange) packet).getChangedBlocks())
                receive(channel, p.getPos(), p.getBlockState(), "SPacketMultiBlockChange");
        }
    }
    private void receive(Channel channel, BlockPos pos, IBlockState state, String type) {
        receipt.receive(channel, pos.toLong(), state.toString(), type, System.nanoTime());
    }
    @SubscribeEvent public void tick(TickEvent.ClientTickEvent event) {
        if (event.phase != TickEvent.Phase.END) return;
        if (world != null && Minecraft.getMinecraft().world != world) receipt.worldChanged();
        receipt.expire(System.nanoTime());
        if (!saved && !receipt.pending()) {
            saved = true;
            final JsonObject result = receipt.snapshot();
            final java.nio.file.Path path = output;
            new Thread(() -> {
                try {
                    java.nio.file.Files.createDirectories(path.getParent());
                    try (java.io.Writer writer = java.nio.file.Files.newBufferedWriter(path, java.nio.charset.StandardCharsets.UTF_8)) {
                        new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(result, writer);
                    }
                } catch (java.io.IOException e) {
                    com.mythos.mythosScriptMod.mythosScriptMod.LOGGER.error("Unable to save terrain interaction review", e);
                }
            }, "terrain-review-save").start();
        }
    }
}
