package com.mythos.mythosScriptMod.mixin;

import com.mythos.mythosScriptMod.shadowbaritone.api.event.events.TickEvent;
import com.mythos.mythosScriptMod.shadowbaritone.api.event.events.type.EventState;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.FieldNode;
import org.objectweb.asm.tree.MethodNode;

import java.io.InputStream;
import java.util.function.BiFunction;

import static org.junit.Assert.*;

/** Reproduces the erased field slot shared with an independently embedded Baritone. */
public class McpBaritoneTickIsolationTest {
    private static final String MIXIN = "com/mythos/mythosScriptMod/shadowbaritone/launch/mixins/MixinMinecraft";
    private static final String PROVIDER = "Ljava/util/function/BiFunction;";

    private enum ForeignState { POST }

    private ClassNode readMixin() throws Exception {
        try (InputStream in = getClass().getClassLoader().getResourceAsStream(MIXIN + ".class")) {
            assertNotNull(in);
            ClassNode node = new ClassNode();
            new ClassReader(in).accept(node, 0);
            return node;
        }
    }

    private String providerField(ClassNode node) {
        String result = null;
        for (FieldNode field : node.fields) {
            if (PROVIDER.equals(field.desc)) {
                assertNull("Expected one embedded tick provider", result);
                result = field.name;
            }
        }
        assertNotNull(result);
        return result;
    }

    @Test
    @SuppressWarnings("unchecked")
    public void embeddedProviderDoesNotOverwriteForeignProvider() throws Exception {
        String embeddedName = providerField(readMixin());
        // Ordinary field merging keys on name and erased descriptor, not generic signature.
        ClassWriter writer = new ClassWriter(0);
        writer.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "TickProviderCarrier", null, "java/lang/Object", null);
        writer.visitField(Opcodes.ACC_PUBLIC, "tickProvider", PROVIDER, null, null).visitEnd();
        if (!"tickProvider".equals(embeddedName)) {
            writer.visitField(Opcodes.ACC_PUBLIC, embeddedName, PROVIDER, null, null).visitEnd();
        }
        org.objectweb.asm.MethodVisitor ctor = writer.visitMethod(Opcodes.ACC_PUBLIC, "<init>", "()V", null, null);
        ctor.visitCode();
        ctor.visitVarInsn(Opcodes.ALOAD, 0);
        ctor.visitMethodInsn(Opcodes.INVOKESPECIAL, "java/lang/Object", "<init>", "()V", false);
        ctor.visitInsn(Opcodes.RETURN);
        ctor.visitMaxs(1, 1);
        ctor.visitEnd();
        writer.visitEnd();
        final byte[] bytes = writer.toByteArray();
        Class<?> carrier = new ClassLoader(getClass().getClassLoader()) {
            Class<?> defineCarrier() { return defineClass("TickProviderCarrier", bytes, 0, bytes.length); }
        }.defineCarrier();
        Object target = carrier.newInstance();
        BiFunction<ForeignState, Object, String> foreign = (state, type) -> state.name();
        carrier.getField("tickProvider").set(target, foreign);
        carrier.getField(embeddedName).set(target, TickEvent.createNextProvider());

        BiFunction<ForeignState, Object, String> original =
                (BiFunction<ForeignState, Object, String>) carrier.getField("tickProvider").get(target);
        assertEquals("POST", original.apply(ForeignState.POST, null));
        BiFunction<EventState, TickEvent.Type, TickEvent> embedded =
                (BiFunction<EventState, TickEvent.Type, TickEvent>) carrier.getField(embeddedName).get(target);
        TickEvent event = embedded.apply(EventState.POST, TickEvent.Type.OUT);
        assertEquals(EventState.POST, event.getState());
        assertEquals(TickEvent.Type.OUT, event.getType());
    }

    @Test
    public void bothCallbacksReferenceOnlyEmbeddedProvider() throws Exception {
        ClassNode node = readMixin();
        String field = providerField(node);
        int callbacks = 0;
        for (MethodNode method : node.methods) {
            if (!"runTick".equals(method.name) && !"postRunTick".equals(method.name)) continue;
            int accesses = 0;
            for (AbstractInsnNode instruction : method.instructions.toArray()) {
                if (!(instruction instanceof FieldInsnNode)) continue;
                FieldInsnNode access = (FieldInsnNode) instruction;
                if (MIXIN.equals(access.owner) && PROVIDER.equals(access.desc)) {
                    assertEquals(field, access.name);
                    accesses++;
                }
            }
            assertTrue("Callback must access its own tick provider", accesses >= 2);
            callbacks++;
        }
        assertEquals(2, callbacks);
    }
}
