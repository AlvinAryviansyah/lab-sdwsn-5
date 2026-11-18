import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Satu simulator untuk semua mode (csv baseline, gym adaptive, gym adaptive + isolasi).
SOURCE = HERE.parent / "honeycomb-sdwsn.cc"
COMPILER = shutil.which("clang++") or shutil.which("g++")


@unittest.skipUnless(COMPILER, "C++ compiler not available")
class TestCppRouteReceiver(unittest.TestCase):
    def test_initial_gym_request_runs_at_flow_start(self):
      source = SOURCE.read_text(encoding="utf-8")
      phase_start = source.index("void PhaseCluster(NodeContainer sensors, NodeContainer sinks)")
      phase_end = source.index("//  TAHAP 4: hybrid IDS", phase_start)
      phase = source[phase_start:phase_end]
      main_start = source.index("int main(int argc, char *argv[])")
      main = source[main_start:]
      self.assertEqual(source.count("RequestGymRoutes(0);"), 1)
      self.assertLess(phase.index("RequestGymRoutes(0);"),
              phase.index("InstallInitialRoutes(sensors, sinks);"))
      self.assertLess(phase.index("InstallInitialRoutes(sensors, sinks);"),
              phase.index("SetupFlow(sensors.Get(i)"))
      self.assertNotIn("RequestGymRoutes(0);", main)
      self.assertIn("Schedule(Seconds(1.3),  &PhaseCluster, sensors, sinks)", main)

    def test_live_adaptive_allows_file_fusion_and_applies_isolation_before_phase_one(self):
        source = SOURCE.read_text(encoding="utf-8")
        phase_start = source.index("static void PhaseIdsHybrid(int n)")
        phase_end = source.index("// Detection-only Phase 2 pilot", phase_start)
        phase = source[phase_start:phase_end]
        main_start = source.index("int main(int argc, char *argv[])")
        main = source[main_start:]

        gym_checks = main[main.index("if (UseGymRoutes())\n  {"):main.index("cfg::routeDir = \"ns3-gym\";")]
        self.assertIn('cfg::idsSource != "none" && cfg::idsSource != "file"', gym_checks)
        self.assertIn("--gymLiveAdaptive/--openGymPort butuh --routeSource=gym", main)
        self.assertIn("if (cfg::gymLiveAdaptive && !useFile)", phase)
        self.assertLess(phase.index("if (h.isolate)"), phase.rindex("RequestGymRoutes(1);"))
        self.assertLess(phase.index("if (h.isolate)"), phase.rindex("ApplyReroute();"))
        self.assertNotIn("if (cfg::gymLiveAdaptive)\n    {", phase)

    def test_csv_route_source_keeps_startup_table_and_skips_gym(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('string   routeSource     = "csv";', source)
        main = source[source.index("int main(int argc, char *argv[])"):]
        # csv: tabel next-hop dimuat dari CSV dan dipasang sebelum simulasi.
        self.assertIn("if (!UseGymRoutes())\n    g_tldqn.Load(", main)
        self.assertIn("UseGymRoutes() ? 0 : InstallInitialRoutes(sensors, sinks)", main)
        self.assertIn("if (UseGymRoutes()) SetupGym();", main)
        self.assertIn('if (cfg::idsSource == "file" && !UseGymRoutes())', main)
        # gym: permintaan rute hanya terjadi di dalam cabang UseGymRoutes().
        phase = source[source.index("void PhaseCluster(NodeContainer sensors, NodeContainer sinks)"):]
        phase = phase[:phase.index("g_ctrlMsgs += 2ull * sensors.GetN();")]
        self.assertLess(phase.index("if (UseGymRoutes())"), phase.index("RequestGymRoutes(0);"))
        hybrid = source[source.index("static void PhaseIdsHybrid(int n)"):]
        hybrid = hybrid[:hybrid.index("// Detection-only Phase 2 pilot")]
        tail = hybrid[hybrid.index("if (h.isolate)"):]
        self.assertLess(tail.index("if (UseGymRoutes())"), tail.rindex("RequestGymRoutes(1);"))

    def test_in_memory_route_validation(self):
        source = SOURCE.read_text(encoding="utf-8")
        start = source.index("class Tldqn\n{")
        end = source.index("\n};", start) + len("\n};")
        receiver = source[start:end]
        program = r'''
#include <cmath>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
using std::string;
using std::vector;
#define NS_FATAL_ERROR(message) do { std::ostringstream error; error << message; throw std::runtime_error(error.str()); } while (0)
#define NS_LOG_UNCOND(message) do {} while (0)
static vector<string> SplitCsv(const string&) { return {}; }
''' + receiver + r'''
int main()
{
  vector<float> action(3203, -1.0f);
  action[0] = 1; action[1] = 0; action[2] = 2;
  vector<float> first{0, 0, 1, 0, 0, 1, 1, 0.25f};
  vector<float> second{1, 0, 0, 1, 0, 1, 1, 0.5f};
  for (int index = 0; index < 8; ++index)
  {
    action[3 + index] = first[index];
    action[11 + index] = second[index];
  }
  Tldqn table;
  table.LoadGym(action, 0, 2, 1, vector<bool>{true, false});
  if (table.Size() != 2 || table.PlannedHops(0) != 2 || !table.ExportMalicious(0)) return 1;
  auto invalid = action;
  invalid[11] = 0;
  try { table.LoadGym(invalid, 0, 2, 1, vector<bool>{true, false}); return 2; }
  catch (const std::runtime_error&) {}
  invalid = action;
  invalid[13] = 0; invalid[14] = 0;
  try { table.LoadGym(invalid, 0, 2, 1, vector<bool>{true, false}); return 3; }
  catch (const std::runtime_error&) {}
  try { table.LoadGym(action, 1, 2, 1, vector<bool>{true, false}); return 4; }
  catch (const std::runtime_error&) {}
  invalid = action;
  invalid[2] = 1;
  try { table.LoadGym(invalid, 0, 2, 1, vector<bool>{true, false}); return 5; }
  catch (const std::runtime_error&) {}
  return 0;
}
'''
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "receiver.cc"
            executable = Path(directory) / "receiver"
            path.write_text(program, encoding="utf-8")
            subprocess.run([COMPILER, "-std=c++20", str(path), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

    def test_simulator_syntax_with_stub_when_headers_exist(self):
        headers = Path(os.environ.get("NS3_HDR_CACHE", "/tmp/ns3-3.48-headers")) / "include"
        if not (headers / "ns3/core-module.h").exists():
            self.skipTest("cached ns-3.48 headers not available")
        subprocess.run([COMPILER, "-std=c++20", "-fsyntax-only",
                        "-I", str(HERE / "test_support"), "-I", str(headers),
                        "-DNS3_LOG_ENABLE", "-DNS3_ASSERT_ENABLE", str(SOURCE)], check=True)
        # Tanpa modul opengym: baseline CSV tetap harus terkompilasi.
        subprocess.run([COMPILER, "-std=c++20", "-fsyntax-only", "-I", str(headers),
                        "-DNS3_LOG_ENABLE", "-DNS3_ASSERT_ENABLE", str(SOURCE)], check=True)


if __name__ == "__main__":
    unittest.main()