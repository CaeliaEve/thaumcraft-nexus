package thaumnexus.agent;

import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.ByteArrayOutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Array;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class ThaumNexusAgentV3 {
    private static volatile Instrumentation instrumentation;

    private ThaumNexusAgentV3() {
    }

    public static void premain(String args, Instrumentation inst) {
        agentmain(args, inst);
    }

    public static void agentmain(String args, Instrumentation inst) {
        instrumentation = inst;
        ClassLoader gameLoader = findGameClassLoader();
        if (gameLoader != null) {
            try {
                Thread.currentThread().setContextClassLoader(gameLoader);
            } catch (SecurityException ignored) {
                // Continue with explicit loader selection in findClass().
            }
        }
        String rawArgs = args == null ? "" : args.trim();
        String mode = "export";
        String outputPath = rawArgs.isEmpty() ? "thaum_nexus_current_note.json" : rawArgs;
        String applyPlanPath = null;
        String loadSlot = null;
        if (rawArgs.startsWith("export|")) {
            outputPath = rawArgs.substring("export|".length());
        } else if (rawArgs.startsWith("inventory|")) {
            mode = "inventory";
            outputPath = rawArgs.substring("inventory|".length());
        } else if (rawArgs.startsWith("load-note|")) {
            String[] parts = rawArgs.split("\\|", -1);
            if (parts.length < 3) {
                outputPath = "thaum_nexus_load_note_result.json";
            } else {
                mode = "load-note";
                loadSlot = parts[1];
                outputPath = parts[2];
            }
        } else if (rawArgs.startsWith("apply|")) {
            String[] parts = rawArgs.split("\\|", -1);
            if (parts.length < 3) {
                outputPath = "thaum_nexus_apply_result.json";
            } else {
                mode = "apply";
                applyPlanPath = parts[1];
                outputPath = parts[2];
            }
        }
        try {
            String json;
            if ("apply".equals(mode)) {
                json = applySolutionJson(applyPlanPath);
            } else if ("inventory".equals(mode)) {
                json = exportInventoryNotesJson();
            } else if ("load-note".equals(mode)) {
                json = loadInventoryNoteJson(loadSlot);
            } else {
                json = exportCurrentNoteJson();
            }
            writeText(outputPath, json);
        } catch (Throwable t) {
            try {
                writeText(outputPath, errorJson(t));
            } catch (Throwable ignored) {
                // Nothing useful can be done here; loadAgent will still return.
            }
        }
    }

    private static String exportCurrentNoteJson() throws Exception {
        Object minecraft = getMinecraft();
        Object screen = readCurrentScreen(minecraft);
        if (screen == null) {
            throw new IllegalStateException("Minecraft currentScreen is null; open the Thaumcraft research table first");
        }

        Object note = readResearchNote(screen);
        if (note == null) {
            throw new IllegalStateException(
                    "current screen is not exposing a Thaumcraft ResearchNoteData; screen=" + screen.getClass().getName());
        }
        Object tile = findResearchTable(screen);
        Object player = readFieldByNames(screen, "player");
        if (player == null) {
            player = readFieldByNames(minecraft, "thePlayer", "field_71439_g");
        }

        StringBuilder out = new StringBuilder(4096);
        appendNoteJson(out, note, screen.getClass().getName(), player, tile);
        return out.toString();
    }

    private static String applySolutionJson(String applyPlanPath) throws Exception {
        if (applyPlanPath == null || applyPlanPath.trim().isEmpty()) {
            throw new IllegalArgumentException("apply plan path is required");
        }
        ApplyPlan plan = readApplyPlan(applyPlanPath);
        Object minecraft = getMinecraft();
        Object screen = readCurrentScreen(minecraft);
        if (screen == null) {
            throw new IllegalStateException("Minecraft currentScreen is null; open the Thaumcraft research table first");
        }
        Object tile = findResearchTable(screen);
        if (tile == null) {
            throw new IllegalStateException("current screen does not expose TileResearchTable; screen=" + screen.getClass().getName());
        }
        Object player = readFieldByNames(screen, "player");
        if (player == null) {
            player = readFieldByNames(minecraft, "thePlayer", "field_71439_g");
        }
        if (player == null) {
            throw new IllegalStateException("unable to locate Minecraft player");
        }

        Object note = readResearchNote(screen);
        if (note == null) {
            throw new IllegalStateException("unable to read current Thaumcraft research note");
        }

        int x = asInt(readFieldByNames(tile, "xCoord", "field_145851_c"), 0);
        int y = asInt(readFieldByNames(tile, "yCoord", "field_145848_d"), 0);
        int z = asInt(readFieldByNames(tile, "zCoord", "field_145849_e"), 0);

        List<SynthesisApplyResult> combineResults = new ArrayList<SynthesisApplyResult>();
        List<PlacementApplyResult> results = new ArrayList<PlacementApplyResult>();
        Map<String, Integer> remainingAspects = new HashMap<String, Integer>();
        int combinesSent = 0;
        int combinesSkipped = 0;
        int sent = 0;
        int skipped = 0;
        for (SynthesisStep step : plan.combines) {
            if (isCancelRequested(plan)) {
                return applyResultJson(
                        screen.getClass().getName(),
                        x,
                        y,
                        z,
                        plan.combines.size(),
                        combinesSent,
                        combinesSkipped,
                        combineResults,
                        plan.placements.size(),
                        sent,
                        skipped,
                        results,
                        "cancelled",
                        "cancel requested before synthesis step");
            }
            Object left = getAspectByTag(step.left);
            Object right = getAspectByTag(step.right);
            Object output = getAspectByTag(step.output);
            if (left == null || right == null || output == null) {
                combinesSkipped++;
                combineResults.add(new SynthesisApplyResult(step, "skipped", "unknown-aspect"));
                continue;
            }
            int leftAvailable = availableAspectAmount(player, tile, left, remainingAspects);
            int rightAvailable = availableAspectAmount(player, tile, right, remainingAspects);
            if (step.left.equals(step.right)) {
                if (leftAvailable < 2) {
                    combinesSkipped++;
                    combineResults.add(new SynthesisApplyResult(step, "skipped", "unavailable-components"));
                    continue;
                }
            } else if (leftAvailable <= 0 || rightAvailable <= 0) {
                combinesSkipped++;
                combineResults.add(new SynthesisApplyResult(step, "skipped", "unavailable-components"));
                continue;
            }
            sendAspectCombinationPacket(player, tile, x, y, z, left, right);
            consumeAspectAmount(left, remainingAspects);
            consumeAspectAmount(right, remainingAspects);
            addAspectAmount(player, tile, output, remainingAspects);
            combinesSent++;
            combineResults.add(new SynthesisApplyResult(step, "sent", ""));
            if (sleepCancelled(plan.delayMs, plan)) {
                return applyResultJson(
                        screen.getClass().getName(),
                        x,
                        y,
                        z,
                        plan.combines.size(),
                        combinesSent,
                        combinesSkipped,
                        combineResults,
                        plan.placements.size(),
                        sent,
                        skipped,
                        results,
                        "cancelled",
                        "cancel requested after synthesis step");
            }
        }

        for (Placement placement : plan.placements) {
            if (isCancelRequested(plan)) {
                return applyResultJson(
                        screen.getClass().getName(),
                        x,
                        y,
                        z,
                        plan.combines.size(),
                        combinesSent,
                        combinesSkipped,
                        combineResults,
                        plan.placements.size(),
                        sent,
                        skipped,
                        results,
                        "cancelled",
                        "cancel requested before placement step");
            }
            PlacementApplyResult result = validatePlacementTarget(note, placement);
            if (!"pending".equals(result.status)) {
                skipped++;
                results.add(result);
                continue;
            }
            Object aspect = getAspectByTag(placement.aspect);
            if (aspect == null) {
                skipped++;
                results.add(new PlacementApplyResult(placement, "skipped", "unknown-aspect"));
                continue;
            }
            int available = availableAspectAmount(player, tile, aspect, remainingAspects);
            if (available <= 0) {
                skipped++;
                results.add(new PlacementApplyResult(placement, "skipped", "unavailable-aspect"));
                continue;
            }
            sendAspectPlacePacket(player, tile, x, y, z, placement, aspect);
            consumeAspectAmount(aspect, remainingAspects);
            sent++;
            results.add(new PlacementApplyResult(placement, "sent", ""));
            if (sleepCancelled(plan.delayMs, plan)) {
                return applyResultJson(
                        screen.getClass().getName(),
                        x,
                        y,
                        z,
                        plan.combines.size(),
                        combinesSent,
                        combinesSkipped,
                        combineResults,
                        plan.placements.size(),
                        sent,
                        skipped,
                        results,
                        "cancelled",
                        "cancel requested after placement step");
            }
        }

        if (sleepCancelled(plan.verifyDelayMs, plan)) {
            return applyResultJson(
                    screen.getClass().getName(),
                    x,
                    y,
                    z,
                    plan.combines.size(),
                    combinesSent,
                    combinesSkipped,
                    combineResults,
                    plan.placements.size(),
                    sent,
                    skipped,
                    results,
                    "cancelled",
                    "cancel requested during verification delay");
        }

        return applyResultJson(
                screen.getClass().getName(),
                x,
                y,
                z,
                plan.combines.size(),
                combinesSent,
                combinesSkipped,
                combineResults,
                plan.placements.size(),
                sent,
                skipped,
                results,
                "ok",
                "");
    }

    private static String exportInventoryNotesJson() throws Exception {
        Object minecraft = getMinecraft();
        Object screen = readCurrentScreen(minecraft);
        if (screen == null) {
            throw new IllegalStateException("Minecraft currentScreen is null; open the Thaumcraft research table first");
        }
        Object container = findContainer(screen);
        if (container == null) {
            throw new IllegalStateException("current screen does not expose an inventory container; screen=" + screen.getClass().getName());
        }
        List<InventoryNote> notes = collectInventoryNotes(container);
        StringBuilder out = new StringBuilder(2048);
        out.append("{\n");
        appendField(out, "source", "client-nbt", true);
        appendField(out, "status", "ok", true);
        appendField(out, "action", "inventory-notes", true);
        appendField(out, "screenClass", screen.getClass().getName(), true);
        appendNumberField(out, "notesFound", notes.size(), true);
        out.append("  \"notes\": [\n");
        for (int i = 0; i < notes.size(); i++) {
            InventoryNote note = notes.get(i);
            out.append("    {\"slot\": ").append(note.slot)
                    .append(", \"slotKind\": ");
            appendJsonString(out, note.slotKind);
            out.append(", \"researchKey\": ");
            appendJsonString(out, note.researchKey);
            out.append(", \"complete\": ").append(note.complete ? "true" : "false")
                    .append(", \"copies\": ").append(note.copies)
                    .append(", \"stackSize\": ").append(note.stackSize)
                    .append("}");
            if (i + 1 < notes.size()) {
                out.append(",");
            }
            out.append("\n");
        }
        out.append("  ]\n");
        out.append("}\n");
        return out.toString();
    }

    private static String loadInventoryNoteJson(String slotText) throws Exception {
        int sourceSlot = Integer.parseInt(slotText == null ? "" : slotText.trim());
        Object minecraft = getMinecraft();
        Object screen = readCurrentScreen(minecraft);
        if (screen == null) {
            throw new IllegalStateException("Minecraft currentScreen is null; open the Thaumcraft research table first");
        }
        Object container = findContainer(screen);
        if (container == null) {
            throw new IllegalStateException("current screen does not expose an inventory container; screen=" + screen.getClass().getName());
        }
        Object player = readFieldByNames(screen, "player");
        if (player == null) {
            player = readFieldByNames(minecraft, "thePlayer", "field_71439_g");
        }
        if (player == null) {
            throw new IllegalStateException("unable to locate Minecraft player");
        }

        Object sourceStack = stackInContainerSlot(container, sourceSlot);
        if (!isResearchNoteStack(sourceStack)) {
            throw new IllegalArgumentException("container slot " + sourceSlot + " does not contain a Thaumcraft research note");
        }
        Object sourceNote = readResearchNoteFromItemStack(sourceStack);
        String sourceKey = asString(readFieldByNames(sourceNote, "key"));
        boolean sourceComplete = asBoolean(readFieldByNames(sourceNote, "complete"), false);
        Object tableStack = stackInContainerSlot(container, 1);
        boolean tableOccupied = tableStack != null;

        if (sourceSlot != 1) {
            if (tableOccupied) {
                clickContainerSlot(minecraft, container, player, 1);
                clickContainerSlot(minecraft, container, player, sourceSlot);
                clickContainerSlot(minecraft, container, player, 1);
            } else {
                clickContainerSlot(minecraft, container, player, sourceSlot);
                clickContainerSlot(minecraft, container, player, 1);
            }
            Thread.sleep(300L);
        }

        StringBuilder out = new StringBuilder();
        out.append("{\n");
        appendField(out, "source", "client-nbt", true);
        appendField(out, "status", "ok", true);
        appendField(out, "action", "load-inventory-note", true);
        appendNumberField(out, "sourceSlot", sourceSlot, true);
        appendNumberField(out, "tableSlot", 1, true);
        appendField(out, "researchKey", sourceKey, true);
        appendBooleanField(out, "sourceComplete", sourceComplete, true);
        appendBooleanField(out, "tableWasOccupied", tableOccupied, false);
        out.append("}\n");
        return out.toString();
    }

    private static Object getMinecraft() throws Exception {
        Class<?> minecraftClass = findClass("net.minecraft.client.Minecraft");
        Object minecraft = invokeStaticNoArg(minecraftClass, "getMinecraft");
        if (minecraft == null) {
            minecraft = invokeStaticNoArg(minecraftClass, "func_71410_x");
        }
        if (minecraft == null) {
            Method[] methods = minecraftClass.getDeclaredMethods();
            for (Method method : methods) {
                if (method.getParameterTypes().length == 0
                        && Modifier.isStatic(method.getModifiers())
                        && method.getReturnType() == minecraftClass) {
                    minecraft = invoke(method, null);
                    if (minecraft != null) {
                        break;
                    }
                }
            }
        }
        if (minecraft == null) {
            Field[] fields = minecraftClass.getDeclaredFields();
            for (Field field : fields) {
                if (Modifier.isStatic(field.getModifiers()) && field.getType() == minecraftClass) {
                    field.setAccessible(true);
                    minecraft = field.get(null);
                    if (minecraft != null) {
                        break;
                    }
                }
            }
        }
        if (minecraft == null) {
            throw new IllegalStateException("unable to locate Minecraft singleton");
        }
        return minecraft;
    }

    private static Object readCurrentScreen(Object minecraft) throws Exception {
        Object screen = readFieldByNames(minecraft, "currentScreen", "field_71462_r");
        if (screen != null) {
            return screen;
        }
        for (Field field : allFields(minecraft.getClass())) {
            if (Modifier.isStatic(field.getModifiers())) {
                continue;
            }
            String typeName = field.getType().getName();
            if (!"net.minecraft.client.gui.GuiScreen".equals(typeName)
                    && !typeName.endsWith(".GuiScreen")
                    && !field.getName().toLowerCase().contains("screen")) {
                continue;
            }
            field.setAccessible(true);
            Object value = field.get(minecraft);
            if (value != null && value.getClass().getName().contains("Gui")) {
                return value;
            }
        }
        return null;
    }

    private static Object readResearchNote(Object screen) throws Exception {
        Object direct = readResearchNoteDirect(screen);
        if (direct != null) {
            return direct;
        }
        DeepSearch search = new DeepSearch();
        return search.findResearchNote(screen, 0);
    }

    private static Object readResearchNoteDirect(Object target) throws Exception {
        if (target == null) {
            return null;
        }
        if (isUsableResearchNote(target)) {
            return target;
        }

        if (target.getClass().getName().equals("elan.tweaks.thaumcraft.research.frontend.integration.adapters.ResearchNotesAdapter")) {
            Object viaAdapter = invokeNoArg(target, "getData");
            if (isUsableResearchNote(viaAdapter)) {
                return viaAdapter;
            }
        }

        Object note = readFieldByNames(target, "note", "data", "researchNoteData");
        if (isUsableResearchNote(note)) {
            return note;
        }

        Object tile = isResearchTable(target)
                ? target
                : readFieldByNames(target, "tileEntity", "tile", "table", "researchTable", "field_147015_w");
        if (tile != null) {
            Object tileData = readFieldByNames(tile, "data");
            if (isUsableResearchNote(tileData)) {
                return tileData;
            }
            Object stack = getStackInSlot(tile, 1);
            if (stack != null) {
                return readResearchNoteFromItemStack(stack);
            }
        }

        return null;
    }

    private static Object findResearchTable(Object root) throws Exception {
        if (isResearchTable(root)) {
            return root;
        }
        Object direct = readFieldByNames(root, "tileEntity", "tile", "table", "researchTable", "field_147015_w");
        if (isResearchTable(direct)) {
            return direct;
        }
        DeepSearch search = new DeepSearch();
        return search.findResearchTable(root, 0);
    }

    private static boolean isResearchTable(Object value) {
        return value != null && "thaumcraft.common.tiles.TileResearchTable".equals(value.getClass().getName());
    }

    private static Object findContainer(Object screen) throws Exception {
        Object container = readFieldByNames(screen, "inventorySlots", "field_147002_h");
        if (container != null) {
            return container;
        }
        return readFieldByNames(screen, "container", "field_147002_h");
    }

    @SuppressWarnings("rawtypes")
    private static List<InventoryNote> collectInventoryNotes(Object container) throws Exception {
        Object slotsObject = readFieldByNames(container, "inventorySlots", "field_75151_b");
        if (!(slotsObject instanceof List)) {
            throw new IllegalStateException("container does not expose inventorySlots");
        }
        List slots = (List) slotsObject;
        List<InventoryNote> notes = new ArrayList<InventoryNote>();
        for (int i = 0; i < slots.size(); i++) {
            Object stack = stackInContainerSlot(container, i);
            if (!isResearchNoteStack(stack)) {
                continue;
            }
            Object note = readResearchNoteFromItemStack(stack);
            String key = asString(readFieldByNames(note, "key"));
            boolean complete = asBoolean(readFieldByNames(note, "complete"), false);
            int copies = asInt(readFieldByNames(note, "copies"), 0);
            int stackSize = asInt(readFieldByNames(stack, "stackSize", "field_77994_a"), 1);
            notes.add(new InventoryNote(i, i == 1 ? "table-note" : "inventory", key, complete, copies, stackSize));
        }
        return notes;
    }

    @SuppressWarnings("rawtypes")
    private static Object stackInContainerSlot(Object container, int slotIndex) throws Exception {
        Object slotsObject = readFieldByNames(container, "inventorySlots", "field_75151_b");
        if (!(slotsObject instanceof List)) {
            return null;
        }
        List slots = (List) slotsObject;
        if (slotIndex < 0 || slotIndex >= slots.size()) {
            return null;
        }
        Object slot = slots.get(slotIndex);
        Method getStack = findMethod(slot.getClass(), "func_75211_c");
        if (getStack == null) {
            getStack = findMethod(slot.getClass(), "getStack");
        }
        return getStack == null ? null : invoke(getStack, slot);
    }

    private static boolean isResearchNoteStack(Object stack) throws Exception {
        if (stack == null) {
            return false;
        }
        Object item = invokeNoArg(stack, "func_77973_b");
        if (item == null) {
            item = invokeNoArg(stack, "getItem");
        }
        if (item == null) {
            return false;
        }
        String className = item.getClass().getName();
        if ("thaumcraft.common.items.ItemResearchNotes".equals(className)) {
            return true;
        }
        try {
            Class<?> researchNotesClass = findClass("thaumcraft.common.items.ItemResearchNotes");
            return researchNotesClass.isAssignableFrom(item.getClass());
        } catch (ClassNotFoundException ignored) {
            return false;
        }
    }

    private static void clickContainerSlot(Object minecraft, Object container, Object player, int slotIndex) throws Exception {
        Object playerController = readFieldByNames(minecraft, "playerController", "field_71442_b");
        if (playerController == null) {
            throw new IllegalStateException("Minecraft playerController was not found");
        }
        int windowId = asInt(readFieldByNames(container, "windowId", "field_75152_c"), 0);
        Class<?> playerClass = findClass("net.minecraft.entity.player.EntityPlayer");
        Method windowClick = findMethod(playerController.getClass(), "func_78753_a",
                int.class, int.class, int.class, int.class, playerClass);
        if (windowClick == null) {
            windowClick = findMethod(playerController.getClass(), "windowClick",
                    int.class, int.class, int.class, int.class, playerClass);
        }
        if (windowClick == null) {
            for (Method method : allMethods(playerController.getClass())) {
                Class<?>[] params = method.getParameterTypes();
                if (params.length == 5
                        && params[0] == int.class
                        && params[1] == int.class
                        && params[2] == int.class
                        && params[3] == int.class
                        && params[4].isAssignableFrom(player.getClass())) {
                    windowClick = method;
                    break;
                }
            }
        }
        if (windowClick == null) {
            throw new IllegalStateException("PlayerControllerMP.windowClick/func_78753_a was not found");
        }
        invoke(windowClick, playerController,
                Integer.valueOf(windowId),
                Integer.valueOf(slotIndex),
                Integer.valueOf(0),
                Integer.valueOf(0),
                player);
    }

    @SuppressWarnings("unchecked")
    private static PlacementApplyResult validatePlacementTarget(Object note, Placement placement) throws Exception {
        Object hexEntriesObject = readFieldByNames(note, "hexEntries");
        if (!(hexEntriesObject instanceof Map)) {
            return new PlacementApplyResult(placement, "skipped", "missing-hexEntries");
        }
        Map<Object, Object> hexEntries = (Map<Object, Object>) hexEntriesObject;
        Object entry = hexEntries.get(placement.key());
        if (entry == null) {
            return new PlacementApplyResult(placement, "skipped", "missing-cell");
        }
        int type = asInt(readFieldByNames(entry, "type"), 0);
        String existingAspect = aspectTag(readFieldByNames(entry, "aspect"));
        if (type == 0) {
            return new PlacementApplyResult(placement, "pending", "");
        }
        if (placement.aspect.equals(existingAspect)) {
            return new PlacementApplyResult(placement, "skipped", "already-placed");
        }
        return new PlacementApplyResult(placement, "skipped", "occupied-type-" + type);
    }

    @SuppressWarnings("rawtypes")
    private static boolean isUsableResearchNote(Object note) throws Exception {
        if (note == null) {
            return false;
        }
        if (!"thaumcraft.common.lib.research.ResearchNoteData".equals(note.getClass().getName())
                && findField(note.getClass(), "hexEntries") == null
                && findField(note.getClass(), "hexes") == null) {
            return false;
        }
        Object hexes = readFieldByNames(note, "hexes");
        if (hexes instanceof Map && !((Map) hexes).isEmpty()) {
            return true;
        }
        Object hexEntries = readFieldByNames(note, "hexEntries");
        return hexEntries instanceof Map && !((Map) hexEntries).isEmpty();
    }

    private static final class DeepSearch {
        private static final int MAX_DEPTH = 10;
        private static final int MAX_NODES = 6000;
        private final Set<Object> visited = Collections.newSetFromMap(new IdentityHashMap<Object, Boolean>());
        private int nodes;

        Object findResearchNote(Object value, int depth) throws Exception {
            if (!enter(value, depth)) {
                return null;
            }
            Object direct = readResearchNoteDirect(value);
            if (direct != null) {
                return direct;
            }
            List<Object> children = childrenOf(value);
            for (Object child : children) {
                Object found = findResearchNote(child, depth + 1);
                if (found != null) {
                    return found;
                }
            }
            return null;
        }

        Object findResearchTable(Object value, int depth) throws Exception {
            if (!enter(value, depth)) {
                return null;
            }
            if (isResearchTable(value)) {
                return value;
            }
            Object direct = readFieldByNames(value, "tileEntity", "tile", "table", "researchTable", "field_147015_w");
            if (isResearchTable(direct)) {
                return direct;
            }
            List<Object> children = childrenOf(value);
            for (Object child : children) {
                Object found = findResearchTable(child, depth + 1);
                if (found != null) {
                    return found;
                }
            }
            return null;
        }

        private boolean enter(Object value, int depth) {
            if (value == null || depth > MAX_DEPTH || nodes++ > MAX_NODES) {
                return false;
            }
            if (isLeaf(value)) {
                return false;
            }
            return visited.add(value);
        }

        private List<Object> childrenOf(Object value) {
            List<Object> out = new ArrayList<Object>();
            Class<?> type = value.getClass();
            if (type.isArray()) {
                int length = Array.getLength(value);
                for (int i = 0; i < length; i++) {
                    addChild(out, Array.get(value, i));
                }
                return out;
            }
            if (value instanceof Iterable) {
                for (Object child : (Iterable<?>) value) {
                    addChild(out, child);
                }
                return out;
            }
            if (value instanceof Map) {
                Map<?, ?> map = (Map<?, ?>) value;
                for (Object child : map.values()) {
                    addChild(out, child);
                }
                return out;
            }
            if (!shouldTraverseFields(type)) {
                return out;
            }
            for (Field field : allFields(type)) {
                if (Modifier.isStatic(field.getModifiers())) {
                    continue;
                }
                try {
                    field.setAccessible(true);
                    addChild(out, field.get(value));
                } catch (Throwable ignored) {
                }
            }
            return out;
        }

        private void addChild(List<Object> out, Object child) {
            if (child != null && !isLeaf(child)) {
                out.add(child);
            }
        }

        private boolean isLeaf(Object value) {
            Class<?> type = value.getClass();
            return type.isPrimitive()
                    || type.isEnum()
                    || value instanceof String
                    || value instanceof Number
                    || value instanceof Boolean
                    || value instanceof Character
                    || value instanceof Class
                    || value instanceof ClassLoader
                    || value instanceof Thread;
        }

        private boolean shouldTraverseFields(Class<?> type) {
            String name = type.getName();
            if (name.startsWith("java.") || name.startsWith("javax.") || name.startsWith("sun.")) {
                return false;
            }
            if (name.startsWith("org.lwjgl.") || name.startsWith("com.google.")) {
                return false;
            }
            if (name.equals("net.minecraft.client.Minecraft")
                    || name.startsWith("net.minecraft.client.multiplayer.")
                    || name.startsWith("net.minecraft.world.")
                    || name.startsWith("net.minecraft.client.renderer.")
                    || name.startsWith("net.minecraft.client.gui.FontRenderer")) {
                return false;
            }
            return name.startsWith("elan.")
                    || name.startsWith("thaumcraft.")
                    || name.startsWith("net.minecraft.client.gui.")
                    || name.startsWith("net.minecraft.inventory.")
                    || name.startsWith("net.minecraft.entity.player.")
                    || name.startsWith("kotlin.jvm.internal.");
        }
    }

    private static Object getStackInSlot(Object tile, int slot) throws Exception {
        for (String name : new String[]{"func_70301_a", "getStackInSlot"}) {
            Method method = findMethod(tile.getClass(), name, int.class);
            if (method != null) {
                return invoke(method, tile, Integer.valueOf(slot));
            }
        }
        for (Method method : allMethods(tile.getClass())) {
            if (method.getParameterTypes().length == 1
                    && method.getParameterTypes()[0] == int.class
                    && method.getReturnType().getName().equals("net.minecraft.item.ItemStack")) {
                return invoke(method, tile, Integer.valueOf(slot));
            }
        }
        return null;
    }

    private static Object readResearchNoteFromItemStack(Object stack) throws Exception {
        Class<?> researchManager = findClass("thaumcraft.common.lib.research.ResearchManager");
        for (Method method : allMethods(researchManager)) {
            if (!Modifier.isStatic(method.getModifiers())) {
                continue;
            }
            if (!"getData".equals(method.getName())) {
                continue;
            }
            if (method.getParameterTypes().length == 1
                    && method.getParameterTypes()[0].isAssignableFrom(stack.getClass())) {
                return invoke(method, null, stack);
            }
        }
        throw new IllegalStateException("ResearchManager.getData(ItemStack) was not found");
    }

    private static Object getAspectByTag(String tag) throws Exception {
        Class<?> aspectClass = findClass("thaumcraft.api.aspects.Aspect");
        for (String name : new String[]{"getAspect"}) {
            Method method = findMethod(aspectClass, name, String.class);
            if (method != null && Modifier.isStatic(method.getModifiers())) {
                return invoke(method, null, tag);
            }
        }
        return null;
    }

    private static void sendAspectPlacePacket(
            Object player,
            Object tile,
            int x,
            int y,
            int z,
            Placement placement,
            Object aspect
    ) throws Exception {
        Class<?> packetClass = findClass("thaumcraft.common.lib.network.playerdata.PacketAspectPlaceToServer");
        Class<?> playerClass = findClass("net.minecraft.entity.player.EntityPlayer");
        Class<?> aspectClass = findClass("thaumcraft.api.aspects.Aspect");
        Constructor<?> constructor = packetClass.getConstructor(
                playerClass, byte.class, byte.class, int.class, int.class, int.class, aspectClass);
        Object packet = constructor.newInstance(
                player,
                Byte.valueOf((byte) placement.q),
                Byte.valueOf((byte) placement.r),
                Integer.valueOf(x),
                Integer.valueOf(y),
                Integer.valueOf(z),
                aspect);

        sendToServer(packet);
    }

    private static void sendAspectCombinationPacket(
            Object player,
            Object tile,
            int x,
            int y,
            int z,
            Object left,
            Object right
    ) throws Exception {
        Class<?> packetClass = findClass("thaumcraft.common.lib.network.playerdata.PacketAspectCombinationToServer");
        Class<?> playerClass = findClass("net.minecraft.entity.player.EntityPlayer");
        Class<?> aspectClass = findClass("thaumcraft.api.aspects.Aspect");
        Constructor<?> constructor = packetClass.getConstructor(
                playerClass,
                int.class,
                int.class,
                int.class,
                aspectClass,
                aspectClass,
                boolean.class,
                boolean.class,
                boolean.class);
        boolean leftBonus = aspectListAmount(readFieldByNames(tile, "bonusAspects"), left) > 0;
        boolean rightBonus = aspectListAmount(readFieldByNames(tile, "bonusAspects"), right) > 0;
        Object packet = constructor.newInstance(
                player,
                Integer.valueOf(x),
                Integer.valueOf(y),
                Integer.valueOf(z),
                left,
                right,
                Boolean.valueOf(leftBonus),
                Boolean.valueOf(rightBonus),
                Boolean.TRUE);

        sendToServer(packet);
    }

    private static void sendToServer(Object packet) throws Exception {
        Class<?> packetHandlerClass = findClass("thaumcraft.common.lib.network.PacketHandler");
        Field instanceField = findField(packetHandlerClass, "INSTANCE");
        if (instanceField == null) {
            throw new IllegalStateException("PacketHandler.INSTANCE was not found");
        }
        instanceField.setAccessible(true);
        Object wrapper = instanceField.get(null);
        Method sendToServer = null;
        for (Method method : allMethods(wrapper.getClass())) {
            if ("sendToServer".equals(method.getName()) && method.getParameterTypes().length == 1) {
                sendToServer = method;
                break;
            }
        }
        if (sendToServer == null) {
            throw new IllegalStateException("SimpleNetworkWrapper.sendToServer was not found");
        }
        invoke(sendToServer, wrapper, packet);
    }

    private static int availableAspectAmount(Object player, Object tile, Object aspect, Map<String, Integer> remaining) throws Exception {
        String tag = aspectTag(aspect);
        Integer cached = remaining.get(tag);
        if (cached != null) {
            return cached.intValue();
        }

        int amount = 0;
        amount += playerAspectPoolAmount(player, aspect);
        Object bonusAspects = readFieldByNames(tile, "bonusAspects");
        amount += aspectListAmount(bonusAspects, aspect);
        remaining.put(tag, Integer.valueOf(amount));
        return amount;
    }

    private static int playerAspectPoolAmount(Object player, Object aspect) throws Exception {
        if (player == null || aspect == null) {
            return 0;
        }
        Object knowledge = getPlayerKnowledge();
        if (knowledge != null) {
            Object username = invokeNoArg(player, "func_70005_c_");
            Method poolMethod = findMethod(knowledge.getClass(), "getAspectPoolFor", String.class, aspect.getClass());
            if (poolMethod == null) {
                Class<?> aspectClass = findClass("thaumcraft.api.aspects.Aspect");
                poolMethod = findMethod(knowledge.getClass(), "getAspectPoolFor", String.class, aspectClass);
            }
            if (poolMethod != null && username != null) {
                Object pool = invoke(poolMethod, knowledge, String.valueOf(username), aspect);
                return asInt(pool, 0);
            }
            Method discoveredMethod = findMethod(knowledge.getClass(), "getAspectsDiscovered", String.class);
            if (discoveredMethod != null && username != null) {
                Object discovered = invoke(discoveredMethod, knowledge, String.valueOf(username));
                return aspectListAmount(discovered, aspect);
            }
        }
        return 0;
    }

    private static void consumeAspectAmount(Object aspect, Map<String, Integer> remaining) throws Exception {
        String tag = aspectTag(aspect);
        Integer amount = remaining.get(tag);
        if (amount != null) {
            remaining.put(tag, Integer.valueOf(Math.max(0, amount.intValue() - 1)));
        }
    }

    private static void addAspectAmount(Object player, Object tile, Object aspect, Map<String, Integer> remaining) throws Exception {
        String tag = aspectTag(aspect);
        Integer amount = remaining.get(tag);
        if (amount == null) {
            amount = Integer.valueOf(availableAspectAmount(player, tile, aspect, remaining));
        }
        remaining.put(tag, Integer.valueOf(amount.intValue() + 1));
    }

    private static Object getPlayerKnowledge() throws Exception {
        Class<?> thaumcraftClass = findClass("thaumcraft.common.Thaumcraft");
        Object proxy = readFieldByNames(thaumcraftClass, "proxy");
        if (proxy == null) {
            return null;
        }
        Object viaMethod = invokeNoArg(proxy, "getPlayerKnowledge");
        if (viaMethod != null) {
            return viaMethod;
        }
        return readFieldByNames(proxy, "playerKnowledge");
    }

    private static int aspectListAmount(Object aspectList, Object aspect) throws Exception {
        if (aspectList == null || aspect == null) {
            return 0;
        }
        Method getAmount = findMethod(aspectList.getClass(), "getAmount", aspect.getClass());
        if (getAmount == null) {
            Class<?> aspectClass = findClass("thaumcraft.api.aspects.Aspect");
            getAmount = findMethod(aspectList.getClass(), "getAmount", aspectClass);
        }
        if (getAmount == null) {
            return 0;
        }
        return asInt(invoke(getAmount, aspectList, aspect), 0);
    }

    @SuppressWarnings("unchecked")
    private static void appendNoteJson(StringBuilder out, Object note, String screenClass, Object player, Object tile) throws Exception {
        String key = asString(readFieldByNames(note, "key"));
        int color = asInt(readFieldByNames(note, "color"), 0);
        boolean complete = asBoolean(readFieldByNames(note, "complete"), false);
        int copies = asInt(readFieldByNames(note, "copies"), 0);
        Object hexesObject = readFieldByNames(note, "hexes");
        Object hexEntriesObject = readFieldByNames(note, "hexEntries");
        Map<Object, Object> hexes = hexesObject instanceof Map ? (Map<Object, Object>) hexesObject : null;
        Map<Object, Object> hexEntries = hexEntriesObject instanceof Map ? (Map<Object, Object>) hexEntriesObject : null;
        if (hexes == null && hexEntries == null) {
            throw new IllegalStateException("ResearchNoteData contains neither hexes nor hexEntries maps");
        }

        List<HexCell> cells = collectCells(hexes, hexEntries);

        out.append("{\n");
        appendField(out, "source", "client-nbt", true);
        appendField(out, "status", "ok", true);
        appendField(out, "screenClass", screenClass, true);
        appendField(out, "researchKey", key, true);
        appendNumberField(out, "color", color, true);
        appendBooleanField(out, "complete", complete, true);
        appendNumberField(out, "copies", copies, true);
        out.append("  \"hexgrid\": [\n");
        for (int i = 0; i < cells.size(); i++) {
            HexCell cell = cells.get(i);
            out.append("    {\"q\": ").append(cell.q)
                    .append(", \"r\": ").append(cell.r)
                    .append(", \"type\": ").append(cell.type);
            if (cell.aspect != null && !cell.aspect.isEmpty()) {
                out.append(", \"aspect\": ");
                appendJsonString(out, cell.aspect);
            }
            out.append("}");
            if (i + 1 < cells.size()) {
                out.append(",");
            }
            out.append("\n");
        }
        out.append("  ],\n");
        appendAspectCountsJson(out, player, tile);
        out.append("}\n");
    }

    @SuppressWarnings("unchecked")
    private static void appendAspectCountsJson(StringBuilder out, Object player, Object tile) throws Exception {
        out.append("  \"aspects\": {\n");
        Map<String, Integer> pool = new HashMap<String, Integer>();
        Map<String, Integer> bonus = new HashMap<String, Integer>();
        Map<String, Integer> available = new HashMap<String, Integer>();

        Class<?> aspectClass = findClass("thaumcraft.api.aspects.Aspect");
        Field aspectsField = findField(aspectClass, "aspects");
        Map<Object, Object> aspectMap = null;
        if (aspectsField != null) {
            aspectsField.setAccessible(true);
            Object value = aspectsField.get(null);
            if (value instanceof Map) {
                aspectMap = (Map<Object, Object>) value;
            }
        }
        if (aspectMap != null) {
            Object bonusAspects = tile == null ? null : readFieldByNames(tile, "bonusAspects");
            for (Map.Entry<Object, Object> entry : aspectMap.entrySet()) {
                Object aspect = entry.getValue();
                String tag = aspectTag(aspect);
                if (tag == null || tag.length() == 0) {
                    tag = String.valueOf(entry.getKey());
                }
                int poolAmount = playerAspectPoolAmount(player, aspect);
                int bonusAmount = aspectListAmount(bonusAspects, aspect);
                pool.put(tag, Integer.valueOf(poolAmount));
                bonus.put(tag, Integer.valueOf(bonusAmount));
                available.put(tag, Integer.valueOf(poolAmount + bonusAmount));
            }
        }

        out.append("    \"pool\": ");
        appendIntMap(out, pool);
        out.append(",\n");
        out.append("    \"bonus\": ");
        appendIntMap(out, bonus);
        out.append(",\n");
        out.append("    \"available\": ");
        appendIntMap(out, available);
        out.append("\n");
        out.append("  }\n");
    }

    private static List<HexCell> collectCells(Map<Object, Object> hexes, Map<Object, Object> hexEntries) throws Exception {
        Set<Object> keys = new LinkedHashSet<Object>();
        if (hexes != null) {
            keys.addAll(hexes.keySet());
        }
        if (hexEntries != null) {
            keys.addAll(hexEntries.keySet());
        }

        List<HexCell> cells = new ArrayList<HexCell>();
        for (Object keyObject : keys) {
            String key = String.valueOf(keyObject);
            Object hex = hexes != null ? hexes.get(keyObject) : null;
            Object entry = hexEntries != null ? hexEntries.get(keyObject) : null;
            int[] coord = hex != null ? coordFromHexObject(hex) : parseHexKey(key);
            int type = entry == null ? 0 : asInt(readFieldByNames(entry, "type"), 0);
            String aspect = null;
            if (entry != null) {
                aspect = aspectTag(readFieldByNames(entry, "aspect"));
            }
            cells.add(new HexCell(coord[0], coord[1], type, aspect));
        }

        Collections.sort(cells, new Comparator<HexCell>() {
            public int compare(HexCell left, HexCell right) {
                int byQ = Integer.compare(left.q, right.q);
                return byQ != 0 ? byQ : Integer.compare(left.r, right.r);
            }
        });
        return cells;
    }

    private static ApplyPlan readApplyPlan(String path) throws Exception {
        String text = readText(path);
        int delayMs = parseOptionalInt(text, "\"delayMs\"\\s*:\\s*(\\d+)", 120);
        int verifyDelayMs = parseOptionalInt(text, "\"verifyDelayMs\"\\s*:\\s*(\\d+)", 600);
        String cancelFile = parseOptionalString(text, "\"cancelFile\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"");
        Pattern combinePattern = Pattern.compile(
                "\\{\\s*\"output\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"\\s*,\\s*\"left\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"\\s*,\\s*\"right\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"\\s*\\}");
        Matcher combineMatcher = combinePattern.matcher(text);
        List<SynthesisStep> combines = new ArrayList<SynthesisStep>();
        while (combineMatcher.find()) {
            combines.add(new SynthesisStep(
                    unescapeJsonString(combineMatcher.group(1)),
                    unescapeJsonString(combineMatcher.group(2)),
                    unescapeJsonString(combineMatcher.group(3))));
        }

        Pattern pattern = Pattern.compile(
                "\\{\\s*\"q\"\\s*:\\s*(-?\\d+)\\s*,\\s*\"r\"\\s*:\\s*(-?\\d+)\\s*,\\s*\"aspect\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"\\s*\\}");
        Matcher matcher = pattern.matcher(text);
        List<Placement> placements = new ArrayList<Placement>();
        while (matcher.find()) {
            placements.add(new Placement(
                    Integer.parseInt(matcher.group(1)),
                    Integer.parseInt(matcher.group(2)),
                    unescapeJsonString(matcher.group(3))));
        }
        if (placements.isEmpty() && combines.isEmpty()) {
            throw new IllegalArgumentException("apply plan contains no placements or combines: " + path);
        }
        return new ApplyPlan(combines, placements, delayMs, verifyDelayMs, cancelFile);
    }

    private static int parseOptionalInt(String text, String regex, int fallback) {
        Matcher matcher = Pattern.compile(regex).matcher(text);
        return matcher.find() ? Integer.parseInt(matcher.group(1)) : fallback;
    }

    private static String parseOptionalString(String text, String regex) {
        Matcher matcher = Pattern.compile(regex).matcher(text);
        return matcher.find() ? unescapeJsonString(matcher.group(1)) : "";
    }

    private static boolean sleepCancelled(int delayMs, ApplyPlan plan) throws InterruptedException {
        if (delayMs <= 0) {
            return isCancelRequested(plan);
        }
        long deadline = System.currentTimeMillis() + delayMs;
        while (System.currentTimeMillis() < deadline) {
            if (isCancelRequested(plan)) {
                return true;
            }
            long remaining = deadline - System.currentTimeMillis();
            Thread.sleep(Math.max(1L, Math.min(50L, remaining)));
        }
        return isCancelRequested(plan);
    }

    private static boolean isCancelRequested(ApplyPlan plan) {
        return plan != null
                && plan.cancelFile != null
                && plan.cancelFile.length() > 0
                && new File(plan.cancelFile).exists();
    }

    private static String readText(String path) throws Exception {
        FileInputStream input = new FileInputStream(path);
        try {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] chunk = new byte[4096];
            int read;
            while ((read = input.read(chunk)) >= 0) {
                buffer.write(chunk, 0, read);
            }
            return new String(buffer.toByteArray(), "UTF-8");
        } finally {
            input.close();
        }
    }

    private static String unescapeJsonString(String value) {
        StringBuilder out = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c != '\\' || i + 1 >= value.length()) {
                out.append(c);
                continue;
            }
            char next = value.charAt(++i);
            switch (next) {
                case '"':
                case '\\':
                case '/':
                    out.append(next);
                    break;
                case 'b':
                    out.append('\b');
                    break;
                case 'f':
                    out.append('\f');
                    break;
                case 'n':
                    out.append('\n');
                    break;
                case 'r':
                    out.append('\r');
                    break;
                case 't':
                    out.append('\t');
                    break;
                case 'u':
                    if (i + 4 < value.length()) {
                        out.append((char) Integer.parseInt(value.substring(i + 1, i + 5), 16));
                        i += 4;
                    }
                    break;
                default:
                    out.append(next);
            }
        }
        return out.toString();
    }

    private static int[] coordFromHexObject(Object hex) throws Exception {
        return new int[]{
                asInt(readFieldByNames(hex, "q"), 0),
                asInt(readFieldByNames(hex, "r"), 0)
        };
    }

    private static int[] parseHexKey(String key) {
        String[] parts = key.contains(":") ? key.split(":", 2) : key.split(",", 2);
        if (parts.length != 2) {
            throw new IllegalArgumentException("cannot parse Thaumcraft hex key: " + key);
        }
        return new int[]{Integer.parseInt(parts[0].trim()), Integer.parseInt(parts[1].trim())};
    }

    private static String aspectTag(Object aspect) throws Exception {
        if (aspect == null) {
            return null;
        }
        Object tag = invokeNoArg(aspect, "getTag");
        if (tag != null) {
            return String.valueOf(tag);
        }
        Object fieldTag = readFieldByNames(aspect, "tag");
        return fieldTag == null ? String.valueOf(aspect) : String.valueOf(fieldTag);
    }

    private static Class<?> findClass(String name) throws ClassNotFoundException {
        Class<?>[] loadedClasses = loadedClasses();
        List<ClassLoader> gameLoaders = candidateGameClassLoaders(loadedClasses);

        Class<?> loadedGameClass = findLoadedClass(name, loadedClasses, gameLoaders, false);
        if (loadedGameClass != null) {
            return loadedGameClass;
        }
        for (ClassLoader loader : gameLoaders) {
            Class<?> loaded = tryLoadClass(name, loader);
            if (loaded != null) {
                return loaded;
            }
        }

        Class<?> anyLoadedClass = findLoadedClass(name, loadedClasses, gameLoaders, true);
        if (anyLoadedClass != null) {
            return anyLoadedClass;
        }

        ClassLoader contextLoader = Thread.currentThread().getContextClassLoader();
        Class<?> contextClass = tryLoadClass(name, contextLoader);
        if (contextClass != null) {
            return contextClass;
        }

        ClassLoader agentLoader = ThaumNexusAgentV3.class.getClassLoader();
        Class<?> agentClass = tryLoadClass(name, agentLoader);
        if (agentClass != null) {
            return agentClass;
        }

        Class<?> systemClass = tryLoadClass(name, ClassLoader.getSystemClassLoader());
        if (systemClass != null) {
            return systemClass;
        }

        Class<?> bootstrapClass = tryLoadClass(name, null);
        if (bootstrapClass != null) {
            return bootstrapClass;
        }

        throw new ClassNotFoundException(name);
    }

    private static Class<?> tryLoadClass(String name, ClassLoader loader) {
        try {
            return Class.forName(name, false, loader);
        } catch (ClassNotFoundException ignored) {
            return null;
        } catch (LinkageError ignored) {
            return null;
        } catch (SecurityException ignored) {
            return null;
        }
    }

    private static Class<?>[] loadedClasses() {
        Instrumentation inst = instrumentation;
        if (inst != null) {
            return inst.getAllLoadedClasses();
        }
        return new Class<?>[0];
    }

    private static ClassLoader findGameClassLoader() {
        List<ClassLoader> loaders = candidateGameClassLoaders(loadedClasses());
        return loaders.isEmpty() ? null : loaders.get(0);
    }

    private static List<ClassLoader> candidateGameClassLoaders(Class<?>[] loadedClasses) {
        LinkedHashSet<ClassLoader> loaders = new LinkedHashSet<ClassLoader>();
        String[] anchors = new String[]{
                "net.minecraft.client.Minecraft",
                "net.minecraft.util.ResourceLocation",
                "cpw.mods.fml.common.Loader",
                "net.minecraft.launchwrapper.Launch",
                "thaumcraft.common.Thaumcraft",
                "thaumcraft.api.aspects.Aspect"
        };
        for (String anchor : anchors) {
            addLoadedClassLoader(loaders, loadedClasses, anchor);
        }
        for (Class<?> candidate : loadedClasses) {
            if (isGameClassName(candidate.getName())) {
                addClassLoader(loaders, candidate.getClassLoader());
            }
        }
        return new ArrayList<ClassLoader>(loaders);
    }

    private static void addLoadedClassLoader(Set<ClassLoader> loaders, Class<?>[] loadedClasses, String name) {
        for (Class<?> candidate : loadedClasses) {
            if (name.equals(candidate.getName())) {
                addClassLoader(loaders, candidate.getClassLoader());
            }
        }
    }

    private static void addClassLoader(Set<ClassLoader> loaders, ClassLoader loader) {
        if (loader != null) {
            loaders.add(loader);
        }
    }

    private static Class<?> findLoadedClass(
            String name,
            Class<?>[] loadedClasses,
            List<ClassLoader> preferredLoaders,
            boolean allowAny
    ) {
        for (ClassLoader loader : preferredLoaders) {
            for (Class<?> candidate : loadedClasses) {
                if (name.equals(candidate.getName()) && candidate.getClassLoader() == loader) {
                    return candidate;
                }
            }
        }
        if (!allowAny) {
            return null;
        }
        ClassLoader agentLoader = ThaumNexusAgentV3.class.getClassLoader();
        Class<?> fallback = null;
        for (Class<?> candidate : loadedClasses) {
            if (!name.equals(candidate.getName())) {
                continue;
            }
            if (fallback == null) {
                fallback = candidate;
            }
            if (candidate.getClassLoader() != agentLoader || !isGameClassName(name)) {
                return candidate;
            }
        }
        return fallback;
    }

    private static boolean isGameClassName(String name) {
        return name.startsWith("net.minecraft.")
                || name.startsWith("thaumcraft.")
                || name.startsWith("cpw.mods.")
                || name.startsWith("net.minecraftforge.")
                || name.startsWith("gregtech.")
                || name.startsWith("com.gtnewhorizons.");
    }

    private static Object readFieldByNames(Object target, String... names) throws Exception {
        if (target == null) {
            return null;
        }
        Class<?> type = target instanceof Class<?> ? (Class<?>) target : target.getClass();
        Object instance = target instanceof Class<?> ? null : target;
        for (String name : names) {
            Field field = findField(type, name);
            if (field != null) {
                field.setAccessible(true);
                return field.get(instance);
            }
        }
        return null;
    }

    private static Field findField(Class<?> type, String name) {
        Class<?> cursor = type;
        while (cursor != null) {
            try {
                return cursor.getDeclaredField(name);
            } catch (NoSuchFieldException ignored) {
                cursor = cursor.getSuperclass();
            }
        }
        return null;
    }

    private static Method findMethod(Class<?> type, String name, Class<?>... parameterTypes) {
        Class<?> cursor = type;
        while (cursor != null) {
            try {
                Method method = cursor.getDeclaredMethod(name, parameterTypes);
                method.setAccessible(true);
                return method;
            } catch (NoSuchMethodException ignored) {
                cursor = cursor.getSuperclass();
            }
        }
        return null;
    }

    private static List<Field> allFields(Class<?> type) {
        List<Field> fields = new ArrayList<Field>();
        Class<?> cursor = type;
        while (cursor != null) {
            Field[] declared = cursor.getDeclaredFields();
            for (Field field : declared) {
                fields.add(field);
            }
            cursor = cursor.getSuperclass();
        }
        return fields;
    }

    private static List<Method> allMethods(Class<?> type) {
        List<Method> methods = new ArrayList<Method>();
        Class<?> cursor = type;
        while (cursor != null) {
            Method[] declared = cursor.getDeclaredMethods();
            for (Method method : declared) {
                method.setAccessible(true);
                methods.add(method);
            }
            cursor = cursor.getSuperclass();
        }
        return methods;
    }

    private static Object invokeStaticNoArg(Class<?> type, String name) throws Exception {
        Method method = findMethod(type, name);
        if (method == null || !Modifier.isStatic(method.getModifiers())) {
            return null;
        }
        return invoke(method, null);
    }

    private static Object invokeNoArg(Object target, String name) throws Exception {
        if (target == null) {
            return null;
        }
        Method method = findMethod(target.getClass(), name);
        if (method == null) {
            return null;
        }
        return invoke(method, target);
    }

    private static Object invoke(Method method, Object target, Object... args) throws Exception {
        try {
            method.setAccessible(true);
            return method.invoke(target, args);
        } catch (InvocationTargetException exc) {
            Throwable cause = exc.getCause();
            if (cause instanceof Exception) {
                throw (Exception) cause;
            }
            if (cause instanceof Error) {
                throw (Error) cause;
            }
            throw exc;
        }
    }

    private static String asString(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static int asInt(Object value, int fallback) {
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        if (value != null) {
            try {
                return Integer.parseInt(String.valueOf(value));
            } catch (NumberFormatException ignored) {
            }
        }
        return fallback;
    }

    private static boolean asBoolean(Object value, boolean fallback) {
        if (value instanceof Boolean) {
            return ((Boolean) value).booleanValue();
        }
        if (value != null) {
            return Boolean.parseBoolean(String.valueOf(value));
        }
        return fallback;
    }

    private static void appendField(StringBuilder out, String name, String value, boolean trailingComma) {
        out.append("  ");
        appendJsonString(out, name);
        out.append(": ");
        appendJsonString(out, value);
        out.append(trailingComma ? ",\n" : "\n");
    }

    private static void appendNumberField(StringBuilder out, String name, int value, boolean trailingComma) {
        out.append("  ");
        appendJsonString(out, name);
        out.append(": ").append(value).append(trailingComma ? ",\n" : "\n");
    }

    private static void appendBooleanField(StringBuilder out, String name, boolean value, boolean trailingComma) {
        out.append("  ");
        appendJsonString(out, name);
        out.append(": ").append(value ? "true" : "false").append(trailingComma ? ",\n" : "\n");
    }

    private static void appendIntMap(StringBuilder out, Map<String, Integer> values) {
        out.append("{");
        List<String> keys = new ArrayList<String>(values.keySet());
        Collections.sort(keys);
        for (int i = 0; i < keys.size(); i++) {
            String key = keys.get(i);
            if (i > 0) {
                out.append(", ");
            }
            appendJsonString(out, key);
            out.append(": ").append(values.get(key).intValue());
        }
        out.append("}");
    }

    private static void appendJsonString(StringBuilder out, String value) {
        out.append('"');
        if (value != null) {
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
                switch (c) {
                    case '"':
                        out.append("\\\"");
                        break;
                    case '\\':
                        out.append("\\\\");
                        break;
                    case '\b':
                        out.append("\\b");
                        break;
                    case '\f':
                        out.append("\\f");
                        break;
                    case '\n':
                        out.append("\\n");
                        break;
                    case '\r':
                        out.append("\\r");
                        break;
                    case '\t':
                        out.append("\\t");
                        break;
                    default:
                        if (c < 0x20) {
                            String hex = Integer.toHexString(c);
                            out.append("\\u");
                            for (int pad = hex.length(); pad < 4; pad++) {
                                out.append('0');
                            }
                            out.append(hex);
                        } else {
                            out.append(c);
                        }
                }
            }
        }
        out.append('"');
    }

    private static String errorJson(Throwable t) {
        StringWriter sw = new StringWriter();
        t.printStackTrace(new PrintWriter(sw));
        StringBuilder out = new StringBuilder();
        out.append("{\n");
        appendField(out, "source", "client-nbt", true);
        appendField(out, "status", "error", true);
        appendField(out, "errorType", t.getClass().getName(), true);
        appendField(out, "error", String.valueOf(t.getMessage()), true);
        appendField(out, "stackTrace", sw.toString(), false);
        out.append("}\n");
        return out.toString();
    }

    private static String applyResultJson(
            String screenClass,
            int x,
            int y,
            int z,
            int combinesRequested,
            int combinesSent,
            int combinesSkipped,
            List<SynthesisApplyResult> combineResults,
            int requested,
            int sent,
            int skipped,
            List<PlacementApplyResult> results,
            String status,
            String message
    ) {
        StringBuilder out = new StringBuilder();
        out.append("{\n");
        appendField(out, "source", "client-nbt", true);
        appendField(out, "status", status == null || status.length() == 0 ? "ok" : status, true);
        appendField(out, "action", "apply-synthesis-and-placements", true);
        if (message != null && message.length() > 0) {
            appendField(out, "message", message, true);
        }
        appendField(out, "screenClass", screenClass, true);
        out.append("  \"tile\": {\"x\": ").append(x).append(", \"y\": ").append(y).append(", \"z\": ").append(z).append("},\n");
        appendNumberField(out, "combinesRequested", combinesRequested, true);
        appendNumberField(out, "combinesSent", combinesSent, true);
        appendNumberField(out, "combinesSkipped", combinesSkipped, true);
        out.append("  \"combines\": [\n");
        for (int i = 0; i < combineResults.size(); i++) {
            SynthesisApplyResult result = combineResults.get(i);
            out.append("    {\"output\": ");
            appendJsonString(out, result.step.output);
            out.append(", \"left\": ");
            appendJsonString(out, result.step.left);
            out.append(", \"right\": ");
            appendJsonString(out, result.step.right);
            out.append(", \"status\": ");
            appendJsonString(out, result.status);
            if (result.reason != null && !result.reason.isEmpty()) {
                out.append(", \"reason\": ");
                appendJsonString(out, result.reason);
            }
            out.append("}");
            if (i + 1 < combineResults.size()) {
                out.append(",");
            }
            out.append("\n");
        }
        out.append("  ],\n");
        appendNumberField(out, "placementsRequested", requested, true);
        appendNumberField(out, "placementsSent", sent, true);
        appendNumberField(out, "placementsSkipped", skipped, true);
        out.append("  \"results\": [\n");
        for (int i = 0; i < results.size(); i++) {
            PlacementApplyResult result = results.get(i);
            out.append("    {\"q\": ").append(result.placement.q)
                    .append(", \"r\": ").append(result.placement.r)
                    .append(", \"aspect\": ");
            appendJsonString(out, result.placement.aspect);
            out.append(", \"status\": ");
            appendJsonString(out, result.status);
            if (result.reason != null && !result.reason.isEmpty()) {
                out.append(", \"reason\": ");
                appendJsonString(out, result.reason);
            }
            out.append("}");
            if (i + 1 < results.size()) {
                out.append(",");
            }
            out.append("\n");
        }
        out.append("  ]\n");
        out.append("}\n");
        return out.toString();
    }

    private static void writeText(String path, String value) throws Exception {
        File file = new File(path);
        File parent = file.getAbsoluteFile().getParentFile();
        if (parent != null && !parent.exists()) {
            parent.mkdirs();
        }
        OutputStreamWriter writer = new OutputStreamWriter(new FileOutputStream(file), "UTF-8");
        try {
            writer.write(value);
        } finally {
            writer.close();
        }
    }

    private static final class HexCell {
        final int q;
        final int r;
        final int type;
        final String aspect;

        HexCell(int q, int r, int type, String aspect) {
            this.q = q;
            this.r = r;
            this.type = type;
            this.aspect = aspect;
        }
    }

    private static final class InventoryNote {
        final int slot;
        final String slotKind;
        final String researchKey;
        final boolean complete;
        final int copies;
        final int stackSize;

        InventoryNote(int slot, String slotKind, String researchKey, boolean complete, int copies, int stackSize) {
            this.slot = slot;
            this.slotKind = slotKind;
            this.researchKey = researchKey;
            this.complete = complete;
            this.copies = copies;
            this.stackSize = stackSize;
        }
    }

    private static final class ApplyPlan {
        final List<SynthesisStep> combines;
        final List<Placement> placements;
        final int delayMs;
        final int verifyDelayMs;
        final String cancelFile;

        ApplyPlan(List<SynthesisStep> combines, List<Placement> placements, int delayMs, int verifyDelayMs, String cancelFile) {
            this.combines = combines;
            this.placements = placements;
            this.delayMs = delayMs;
            this.verifyDelayMs = verifyDelayMs;
            this.cancelFile = cancelFile;
        }
    }

    private static final class SynthesisStep {
        final String output;
        final String left;
        final String right;

        SynthesisStep(String output, String left, String right) {
            this.output = output;
            this.left = left;
            this.right = right;
        }
    }

    private static final class Placement {
        final int q;
        final int r;
        final String aspect;

        Placement(int q, int r, String aspect) {
            this.q = q;
            this.r = r;
            this.aspect = aspect;
        }

        String key() {
            return q + ":" + r;
        }
    }

    private static final class PlacementApplyResult {
        final Placement placement;
        final String status;
        final String reason;

        PlacementApplyResult(Placement placement, String status, String reason) {
            this.placement = placement;
            this.status = status;
            this.reason = reason;
        }
    }

    private static final class SynthesisApplyResult {
        final SynthesisStep step;
        final String status;
        final String reason;

        SynthesisApplyResult(SynthesisStep step, String status, String reason) {
            this.step = step;
            this.status = status;
            this.reason = reason;
        }
    }
}

