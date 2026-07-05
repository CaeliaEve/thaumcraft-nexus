package thaumnexus.agent;

import com.sun.tools.attach.VirtualMachine;
import com.sun.tools.attach.VirtualMachineDescriptor;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class ThaumNexusAttacher {
    private ThaumNexusAttacher() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            usage();
            System.exit(2);
        }

        String agentJar = new File(args[0]).getAbsoluteFile().getPath();
        String agentArgs;
        String pid;
        if ("export".equals(args[1])) {
            if (args.length < 3 || args.length > 4) {
                usage();
                System.exit(2);
                return;
            }
            String outputJson = new File(args[2]).getAbsoluteFile().getPath();
            agentArgs = "export|" + outputJson;
            pid = args.length == 4 ? args[3] : null;
        } else if ("inventory".equals(args[1])) {
            if (args.length < 3 || args.length > 4) {
                usage();
                System.exit(2);
                return;
            }
            String outputJson = new File(args[2]).getAbsoluteFile().getPath();
            agentArgs = "inventory|" + outputJson;
            pid = args.length == 4 ? args[3] : null;
        } else if ("load-note".equals(args[1])) {
            if (args.length < 4 || args.length > 5) {
                usage();
                System.exit(2);
                return;
            }
            String slot = args[2];
            String resultJson = new File(args[3]).getAbsoluteFile().getPath();
            agentArgs = "load-note|" + slot + "|" + resultJson;
            pid = args.length == 5 ? args[4] : null;
        } else if ("apply".equals(args[1])) {
            if (args.length < 4 || args.length > 5) {
                usage();
                System.exit(2);
                return;
            }
            String planJson = new File(args[2]).getAbsoluteFile().getPath();
            String resultJson = new File(args[3]).getAbsoluteFile().getPath();
            agentArgs = "apply|" + planJson + "|" + resultJson;
            pid = args.length == 5 ? args[4] : null;
        } else {
            if (args.length > 3) {
                usage();
                System.exit(2);
                return;
            }
            // Backward-compatible form:
            //   <agent.jar> <output.json> [pid]
            String outputJson = new File(args[1]).getAbsoluteFile().getPath();
            agentArgs = "export|" + outputJson;
            pid = args.length == 3 ? args[2] : null;
        }
        if (pid == null || pid.trim().isEmpty()) {
            pid = chooseMinecraftJvm();
        }

        System.out.println("ThaumNexusAttacher: attaching to JVM pid=" + pid);
        VirtualMachine vm = null;
        try {
            vm = VirtualMachine.attach(pid);
            vm.loadAgent(agentJar, agentArgs);
        } finally {
            if (vm != null) {
                vm.detach();
            }
        }
        System.out.println("ThaumNexusAttacher: agent completed " + args[1]);
    }

    private static void usage() {
        System.err.println("Usage:");
        System.err.println("  java ... thaumnexus.agent.ThaumNexusAttacher <agent.jar> <output.json> [pid]");
        System.err.println("  java ... thaumnexus.agent.ThaumNexusAttacher <agent.jar> export <output.json> [pid]");
        System.err.println("  java ... thaumnexus.agent.ThaumNexusAttacher <agent.jar> inventory <output.json> [pid]");
        System.err.println("  java ... thaumnexus.agent.ThaumNexusAttacher <agent.jar> load-note <container-slot> <result.json> [pid]");
        System.err.println("  java ... thaumnexus.agent.ThaumNexusAttacher <agent.jar> apply <plan.json> <result.json> [pid]");
    }

    private static String chooseMinecraftJvm() {
        List<VirtualMachineDescriptor> descriptors = VirtualMachine.list();
        List<VirtualMachineDescriptor> candidates = new ArrayList<VirtualMachineDescriptor>();
        for (VirtualMachineDescriptor descriptor : descriptors) {
            if (isMinecraftLike(descriptor.displayName())) {
                candidates.add(descriptor);
            }
        }

        if (candidates.isEmpty()) {
            System.err.println("No Minecraft/Forge/GTNH JVM was found. Running JVMs:");
            for (VirtualMachineDescriptor descriptor : descriptors) {
                System.err.println("  " + descriptor.id() + "  " + descriptor.displayName());
            }
            throw new IllegalStateException("open the GTNH client first, then open the Thaumcraft research table");
        }

        if (candidates.size() > 1) {
            System.err.println("Multiple Minecraft-like JVMs found; using the first one. Pass [pid] to choose explicitly:");
            for (VirtualMachineDescriptor descriptor : candidates) {
                System.err.println("  " + descriptor.id() + "  " + descriptor.displayName());
            }
        }

        return candidates.get(0).id();
    }

    private static boolean isMinecraftLike(String displayName) {
        String value = displayName == null ? "" : displayName.toLowerCase(Locale.ROOT);
        return value.contains("minecraft")
                || value.contains("launchwrapper")
                || value.contains("net.minecraft.launchwrapper.launch")
                || value.contains("org.prismlauncher.entrypoint")
                || value.contains("org.multimc.entrypoint")
                || value.contains("forge")
                || value.contains("gtnh")
                || value.contains("gradlestart");
    }
}
